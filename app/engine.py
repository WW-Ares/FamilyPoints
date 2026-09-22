# -*- coding: utf-8 -*-
"""
核心引擎。

所有规则都在这里落地。任何一个可调的数字都走 db.cfg()，代码里不写死。
所有余额都由流水求和得出，不存冗余余额字段。
"""
import json
import random
import re
from datetime import datetime, time, timedelta

import db
import notify as N
import seed_data


def clean_icon(v):
    """图标值入库前先过一遍。

    这个值最终会被拼进 HTML。渲染时前端还会 esc 一次，这里再掐一道，
    等于把风险挡在离展示最远的地方 —— 存进去的东西已经是干净的。

    不在清单里的 token 不拦。前端 iconToken 认不出来会自己回落到占位圆，
    而且以后只想往 web/icons 里丢一个 SVG、不想连后端一起发版的时候，
    不必两边同时改版本号。
    """
    s = "" if v is None else str(v).strip()
    if not s:
        return ""
    # emoji 是码点、汉字是码点，都不含这几个字符；掐掉它们不影响任何正常用法
    return re.sub(r"[<>&\"'\\/]", "", s)[:16]


# 头像比图标严。图标值可能是一个 emoji 或一个汉字，得让它们过；
# 头像只有「我们自己做的那几款」这一种来源，值就是一个文件名（avatars/<token>.svg）。
# 所以这里只放行字母、数字和下划线：`..`、`/`、`\`、点号全被掐掉，
# 拼进路径也飞不出 web/avatars 这个目录一步。认不出来的值前端回落成名字首字，
# 不报错 —— 老库里那些存着「爸爸」两个字的记录不该因为加头像就显示不出来。
AVATAR_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
# v36 起的 40 款是 B01 / D01 这种形状（一位字母 + 两位数字）。
AVATAR_ID_RE = re.compile(r"^[A-Za-z]\d{2}$")


def clean_avatar(v):
    """值 = avatars/<值>.svg 的文件名，形状对上就留着，对不上一律清空。

    大小写要当回事：NAS 上跑的是 Linux，文件名区分大小写，库里存 b01
    就找不到 B01.svg（Windows 上能跑出来，装到 NAS 上就是一片空白）。
    所以「一位字母 + 两位数字」这种形状统一抬成大写，其余（老库里 girl_1
    这类下划线的值）按小写形状留着，等 _migrate_v36 把它们换成新 ID。
    """
    s = "" if v is None else str(v).strip()
    if not AVATAR_RE.match(s):
        return ""
    if AVATAR_ID_RE.match(s):
        return s.upper()
    return s.lower()

# ---------------------------------------------------------------------------
# 日期与周期
# ---------------------------------------------------------------------------
KINDS = {
    "daily_score": "每日打分",
    "explore": "星探时刻",
    "task_energy": "任务·周能量",
    "task_stardust": "任务·星尘",
    # v28：普通任务的券/卡奖励从前一律写成 repair（「修复任务」），
    # 家长看到「修复任务」会以为孩子挨罚了，其实是他做完事拿的奖。
    # 修复任务本身还是 repair，两者分开。
    "task_item": "任务·发券与卡",
    "box_free": "宝箱·达标发放",
    "box_purchase": "宝箱·直购",
    "shop_ticket": "商店·买券",
    "shop_card": "商店·买卡",
    "cash_exchange": "兑换零花钱",
    "fine": "罚款",
    "pool_deposit": "许愿池投币",
    "repair": "修复任务",
    "expire_refund": "到期折半返还",
    "renew": "卡片续期",
    "fragment": "碎片",
    "overtime": "加时申请",
    "help": "求助",
    "holiday_delay": "假期顺延",
    "adjust": "手动调整",
    "correction": "修正",
    "carryover": "存量结转",
    "ticket_use": "券核销",
    "card_effect": "卡片生效",
    "cash_bonus": "零花钱加倍",
    "card_use": "使用卡片",
    # v28 补：这两个早就在写流水了，只是没登记过名字，
    # 界面上一直显示成英文 key（升级奖励那张还曾被当成「手动调整」——
    # 家长问「券哪来的」，账本给的答案是「手动调整」，等于没答）。
    "level_up": "升级奖励",
    "box_reroll": "宝箱重抽",
}


def parse_day(s):
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def fmt(d):
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 时钟
# ---------------------------------------------------------------------------
# 「现在」在整套规则里到处被读到：券的五道闸门有三道看时刻（间隔、晚间、硬停止）、
# 周期按天切、加时窗口按小时算、数据补录只认最近几天。不给一个统一的时钟口子，
# 这些测试就只能挑某几个钟点跑才不会挂 —— 而挑钟点跑出来的绿，不算数。
#
# 生产路径上没有任何地方调用 freeze_clock，_CLOCK 永远是 None，走真实时间。
_CLOCK = None


def _dtnow():
    """「现在」的 datetime。这是全文件唯一一个读真实时钟的地方。"""
    return (datetime.strptime(_CLOCK, "%Y-%m-%d %H:%M:%S") if _CLOCK else datetime.now())


def freeze_clock(at=None):
    """把「现在」钉在 at（'YYYY-MM-DD HH:MM:SS'）。传 None 恢复真实时钟。

    只给测试用。传进来的时刻会同时决定日期，所以冻结之后 today() 也跟着变。
    """
    global _CLOCK
    _CLOCK = (at or None)
    if _CLOCK:
        # 早失败：格式写错的时钟比不冻结更危险，它会静默地让 today() 返回垃圾
        datetime.strptime(_CLOCK, "%Y-%m-%d %H:%M:%S")
    return _CLOCK


def now():
    return _dtnow().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return fmt(_dtnow().date())


def days_back(n):
    """n 天前那天，含今天算第 1 天（days_back(1) 就是今天）。

    走同一个可冻结的时钟：不能用 SQLite 的 date('now')，那样测试里
    freeze_clock 就冻不住了，跨零点那种断言会变成看服务器心情。
    """
    return fmt(_dtnow().date() - timedelta(days=max(0, int(n) - 1)))


def week_start_of(day):
    """按设置里的周期起点，返回 day 所属周期的第一天。"""
    d = parse_day(day)
    start_wd = int(db.cfg("cycle.start_weekday", 5))   # 5 = 周六
    delta = (d.weekday() - start_wd) % 7
    return fmt(d - timedelta(days=delta))


def cycle_bounds(start_date):
    n = int(db.cfg("cycle.length_days", 7))
    s = parse_day(start_date)
    return fmt(s), fmt(s + timedelta(days=n - 1))


# ---------------------------------------------------------------------------
# 假期
# ---------------------------------------------------------------------------
def holiday_at(day):
    return db.query_one(
        "SELECT * FROM holiday WHERE start_date<=? AND end_date>=? ORDER BY start_date LIMIT 1",
        (day, day))


def is_transition(day):
    """假期首尾各若干天为过渡日，不计分。"""
    n = int(db.cfg("holiday.transition_days", 1))
    for h in db.query("SELECT * FROM holiday"):
        s, e = h["start_date"], h["end_date"]
        head_end = fmt(parse_day(s) + timedelta(days=n - 1))
        tail_start = fmt(parse_day(e) - timedelta(days=n - 1))
        if s <= day <= head_end or tail_start <= day <= e:
            return True
    return False


def day_mode(day):
    """school 或 holiday。"""
    if not db.cfg("holiday.mode_auto", True):
        return "school"
    return "holiday" if holiday_at(day) else "school"


def dimensions(mode="school"):
    rows = db.query("SELECT * FROM dimension WHERE active=1 ORDER BY sort")
    out = []
    for r in rows:
        name = r["name"]
        if mode == "holiday" and r["holiday_name"]:
            name = r["holiday_name"]
        out.append({
            "id": r["id"], "code": r["code"], "name": name,
            "base_name": r["name"], "meaning": r["meaning"],
            "icon": r["icon"], "score": r["score"], "sort": r["sort"],
            "renamed": bool(mode == "holiday" and r["holiday_name"]),
        })
    return out


def countable_days(start_date, end_date):
    s, e = parse_day(start_date), parse_day(end_date)
    n = 0
    d = s
    while d <= e:
        if not is_transition(fmt(d)):
            n += 1
        d += timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
# 谁在游戏循环里（v13）
# ---------------------------------------------------------------------------
PARENT_MSG = "家长只负责打分，不参与被打分与奖励"


def is_player(member_id):
    """进游戏循环的只有孩子。

    v13 起家长只打分、不参与被打分：没有每日 7 分、没有周能量、没有周期、
    没有宝箱、没有星尘券卡，也不进成长报告和任何对比视图。
    判断依据是数据库里的 role，不信任调用方传来的身份，
    所以任何路径（含脚本直接调用）都绕不过去。
    """
    m = db.query_one("SELECT role FROM member WHERE id=?", (member_id,))
    return bool(m and m["role"] == "child")


JUDGE_MSG = "只有爸爸妈妈能打分"


def is_judge(member_id):
    """能打分的人只有家长（裁判席）。

    这条和 is_player() 是一对，合起来把「谁打分、谁被打分」两边都钉死。
    只挡住「给孩子打分」这一半是不够的：孩子如果能给自己打分，
    「当天学习任务已完成」这个娱乐券前置条件就随时可以自己刷满，等于没有。
    所以判定同样走数据库里的 role，不看调用方怎么说。
    """
    m = db.query_one("SELECT role FROM member WHERE id=?", (member_id,))
    return bool(m and m["role"] == "parent")


# ---------------------------------------------------------------------------
# 周期
# ---------------------------------------------------------------------------
def get_or_create_cycle(member_id, day):
    if not is_player(member_id):
        return None                      # 家长连周期记录都不建
    start = week_start_of(day)
    row = db.query_one("SELECT * FROM cycle WHERE member_id=? AND start_date=?", (member_id, start))
    if row:
        return row
    s, e = cycle_bounds(start)
    cd = countable_days(s, e)
    total = (parse_day(e) - parse_day(s)).days + 1
    ratio = round(cd / float(total), 4) if total else 1.0
    cid = db.execute(
        "INSERT INTO cycle (member_id, start_date, end_date, countable_days, threshold_ratio, status)"
        " VALUES (?,?,?,?,?,'open')", (member_id, s, e, cd, ratio))
    return db.query_one("SELECT * FROM cycle WHERE id=?", (cid,))


def recalc_cycle(cycle_id):
    """周能量 = 每日固定分 + 额外加分（星探 / 任务）。"""
    c = db.query_one("SELECT * FROM cycle WHERE id=?", (cycle_id,))
    if not c:
        return None
    fixed = db.query_one(
        "SELECT COALESCE(SUM(value),0) v FROM score_entry WHERE cycle_id=? AND is_fixed=1 AND voided=0",
        (cycle_id,))["v"]
    bonus = db.query_one(
        "SELECT COALESCE(SUM(delta_energy),0) v FROM ledger WHERE cycle_id=? AND voided=0"
        " AND kind IN ('explore','task_energy','adjust')", (cycle_id,))["v"]
    db.execute("UPDATE cycle SET fixed_score=?, bonus_energy=?, energy=? WHERE id=?",
               (fixed, bonus, fixed + bonus, cycle_id))
    return db.query_one("SELECT * FROM cycle WHERE id=?", (cycle_id,))


def current_cycle(member_id, day=None):
    return get_or_create_cycle(member_id, day or today())


# ---------------------------------------------------------------------------
# 流水
# ---------------------------------------------------------------------------
def add_ledger(member_id, kind, *, cycle_id=None, day=None, energy=0, stardust=0, debt=0,
               fragment=0, ticket=0, minutes=0, ref_type="", ref_id=None,
               note="", operator_id=None, meta=None):
    return db.execute(
        """INSERT INTO ledger (member_id, cycle_id, ts, day, kind, delta_energy, delta_stardust,
             delta_debt, delta_fragment, delta_ticket, delta_minutes, ref_type, ref_id, note,
             operator_id, meta)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (member_id, cycle_id, now(), day, kind, energy, stardust, debt, fragment, ticket, minutes,
         ref_type, ref_id, note, operator_id, json.dumps(meta or {}, ensure_ascii=False)))


def stardust_balance(member_id):
    return round(db.query_one(
        "SELECT COALESCE(SUM(delta_stardust),0) v FROM ledger WHERE member_id=? AND voided=0",
        (member_id,))["v"], 2)


def debt_balance(member_id):
    """未结清的欠款（正数表示欠多少星尘）。不出现负星尘，欠款单独记账。"""
    return round(db.query_one(
        "SELECT COALESCE(SUM(delta_debt),0) v FROM ledger WHERE member_id=? AND voided=0",
        (member_id,))["v"], 2)


def fragment_balance(member_id):
    return round(db.query_one(
        "SELECT COALESCE(SUM(delta_fragment),0) v FROM ledger WHERE member_id=? AND voided=0",
        (member_id,))["v"], 2)


def minutes_balance(member_id, day=None):
    """分钟的净额：正数=今天还余出多少，负数=欠着多少。

    关键的一句是「白天拿到的分钟，过了今天就没了」。加时卡、箱子开出的
    「加时 60 分钟」都是按天给的额度，不是存进户头的钱。以前直接把
    delta_minutes 全表求和，于是今天多出来的 60 分钟会一直挂在账上，
    把后面两次 −30 的扣分整个吃掉：孩子今天运气好开出一次加时，
    接下来两周做错事都不用还。这不是「券允许负库存」，是白送的免罚次数。

    欠账要能跨天留着（那是还没还完的），只有正余额按天作废。
    """
    day = day or today()
    rows = db.query(
        "SELECT day, COALESCE(SUM(delta_minutes),0) v FROM ledger"
        " WHERE member_id=? AND voided=0 AND delta_minutes<>0 AND day<=?"
        " GROUP BY day ORDER BY day", (member_id, day))
    carry = 0.0
    for r in rows:
        carry += float(r["v"] or 0)
        # 这一天结完账是正余额，说明昨天给的时间他没用完 —— 没用完就没用完，
        # 不能折成明天的额度。
        if carry > 0 and r["day"] < day:
            carry = 0.0
    return round(carry, 2)


def minutes_debt(member_id, day=None):
    """欠多少分钟娱乐时间（正数表示欠）。

    规则里允许「券的负库存」：孩子表现不好要扣 15 分钟，但他手上可能一张券都没有
    （券刚花完很常见），这笔扣罚不能落空。做法是单独记一条分钟账，
    核销时先从今天的额度里扣，周期结算再按条件清零或保留。
    券的张数账（ledger_item）不动，避免「欠 1 张券」这种界面没法解释的状态。
    """
    return round(-min(0.0, minutes_balance(member_id, day)), 2)


def minutes_credit(member_id, day=None):
    """今天还剩多少余出来的分钟。欠着的时候是 0 —— 余出来的先拿去还账。"""
    return round(max(0.0, minutes_balance(member_id, day)), 2)


def minutes_debt_today(member_id, day=None):
    """今天已经扣掉多少分钟（用来卡单日 −30 的上限）。"""
    day = day or today()
    return round(-min(0.0, db.query_one(
        "SELECT COALESCE(SUM(delta_minutes),0) v FROM ledger"
        " WHERE member_id=? AND voided=0 AND day=? AND delta_minutes<0", (member_id, day))["v"]), 2)


def item_balance(member_id, item_id):
    return round(db.query_one(
        "SELECT COALESCE(SUM(qty_delta),0) v FROM ledger_item WHERE member_id=? AND item_id=?",
        (member_id, item_id))["v"], 2)


# ---------------------------------------------------------------------------
# 道具发放与消耗
# ---------------------------------------------------------------------------
def item_by_code(code):
    return db.query_one("SELECT * FROM item WHERE code=?", (code,))


def add_ledger_item(ledger_id, member_id, item_id, qty, reason, holding_id=None):
    db.execute(
        "INSERT INTO ledger_item (ledger_id, member_id, item_id, holding_id, qty_delta, reason, ts)"
        " VALUES (?,?,?,?,?,?,?)", (ledger_id, member_id, item_id, holding_id, qty, reason, now()))


def grant_item(member_id, item_id, qty=1.0, source="box", note="", ref_type="", ref_id=None,
               operator_id=None, auto_fragment=True, kind=None, cycle_id=None):
    """发一件道具，返回 (holding_id, 实际入账数量, 拆成的碎片数)。"""
    it = db.query_one("SELECT * FROM item WHERE id=?", (item_id,))
    if not it:
        return None, 0, 0
    if kind is None:
        # source → kind。漏登记会写成「手动调整」这种看不出所以然的类型，
        # 而家长正是靠这个字段回答「这东西哪来的」。（v28 补 levelup）
        kind = {"box": "box_free", "shop": "shop_card", "task": "repair",
                "levelup": "level_up"}.get(source, "adjust")
    expires = None
    if it["shelf_life_days"]:
        expires = fmt(parse_day(today()) + timedelta(days=int(it["shelf_life_days"])))
    lid = add_ledger(member_id, kind, cycle_id=cycle_id, ref_type=ref_type or "item", ref_id=ref_id,
                     note=note or ("获得 " + it["name"]),
                     operator_id=operator_id, meta={"item": it["code"]})
    hid = db.execute(
        "INSERT INTO holding (member_id, item_id, qty, source, acquired_at, expires_at, note)"
        " VALUES (?,?,?,?,?,?,?)", (member_id, item_id, qty, source, now(), expires, note))
    add_ledger_item(lid, member_id, item_id, qty, note or "获得", hid)

    frag = 0
    if auto_fragment and it["max_hold"]:
        frag = enforce_max_hold(member_id, it, operator_id=operator_id)
    return hid, qty, frag


def enforce_max_hold(member_id, item, operator_id=None):
    """超过持有上限的部分自动拆碎片（只有宝箱开出的能拆，买来的不拆）。"""
    total = item_balance(member_id, item["id"])
    if not item["max_hold"] or total <= item["max_hold"]:
        return 0
    over = total - item["max_hold"]
    if item["fragment_value"] <= 0:
        return 0
    left = over
    collected = 0.0
    for h in db.query("SELECT * FROM holding WHERE member_id=? AND item_id=? AND qty>0"
                      " ORDER BY acquired_at", (member_id, item["id"])):
        if left <= 1e-9:
            break
        if h["source"] == "shop":      # 商店买的卡不拆（碎片只从打出来的重复卡里产生）
            continue
        take = min(h["qty"], left)
        db.execute("UPDATE holding SET qty=qty-? WHERE id=?", (take, h["id"]))
        left -= take
        collected += take
    if collected <= 0:
        return 0
    got = round(collected * item["fragment_value"], 2)
    lid = add_ledger(member_id, "fragment", fragment=got,
                     note="重复卡拆解：%s ×%g" % (item["name"], collected),
                     operator_id=operator_id, meta={"item": item["code"], "qty": collected})
    db.execute("INSERT INTO fragment_use (member_id, qty, kind, note, ts) VALUES (?,?,?,?,?)",
               (member_id, got, "gain", "重复卡拆解 " + item["name"], now()))
    add_ledger_item(lid, member_id, item["id"], -collected, "超上限拆碎片")
    return got


def consume_item(member_id, item_id, qty=1.0, note="", kind="adjust", operator_id=None):
    """FIFO 消耗（先到期先用）。返回剩余不足的数量（负数表示不足）。"""
    if not is_player(member_id):
        return -1
    # 负数 qty 会让「余额 < qty」恒为假、进而在 add_ledger_item 里写成正数，
    # 等于凭空造道具。这一道必须在这里，接口层的校验只是早一点报错。
    qty = float(qty or 0)
    if qty <= 0:
        return -1
    if item_balance(member_id, item_id) < qty:
        return -1
    left = qty
    for h in db.query("SELECT * FROM holding WHERE member_id=? AND item_id=? AND qty>0"
                      " ORDER BY COALESCE(expires_at,'9999-12-31'), acquired_at", (member_id, item_id)):
        if left <= 0:
            break
        take = min(h["qty"], left)
        db.execute("UPDATE holding SET qty=qty-? WHERE id=?", (take, h["id"]))
        left -= take
    lid = add_ledger(member_id, kind, note=note, operator_id=operator_id,
                     meta={"item_id": item_id, "qty": qty})
    add_ledger_item(lid, member_id, item_id, -qty, note or "使用")
    db.execute("INSERT INTO item_use (member_id, item_id, qty, ts, note) VALUES (?,?,?,?,?)",
               (member_id, item_id, qty, now(), note))
    return 0


# ---------------------------------------------------------------------------
# 券核销：机器闸门 + 家长点头（v14，v32 重做「一轮」的判定）
# ---------------------------------------------------------------------------
# 券是孩子自己挣来的，但用的时候要家长点一下头。在点头之前，娱乐券先过
# 机器闸门（要不要等休息 / 这一轮还要得了几张 / 硬停止时间），不过的直接
# 在孩子那边就拒掉，不拿一堆明显不合规的申请去烦家长。
#
# v32 之前，「休息」挂在每一段娱乐的结束上：孩子用 1 张、30 分钟放完就被
# 锁 60 分钟，第 2 张点不动。实际要的是「一轮」用满才休息 —— 白天连续
# 3 张、晚间连续 2 张，中间可以一张一张地续。
#
# 一轮 = 一段连续娱乐。判定「连续」只看一个数：后一张的提交时刻
# （ticket_request.ts）距前一张结束（end_at）有没有超过
# ticket.renew_within_minutes 分钟（默认 10）。提前提交、上一张还在放，
# 也算连续。一轮在两种情况下结束，都锁 ticket.cooldown_minutes 分钟：
#   ① 张数用满（白天 3 张 / 晚间 2 张，加时各 +1）
#   ② 超过 renew_within_minutes 分钟没续
# 第二条不能省：少了它，孩子每张之间歇 11 分钟慢慢用，一天下来永远攒不到
# 3 张，冷却就完全失效了。
#
# 窗口按**提交时刻**判，时段闸门按**核销时刻**判。家长慢 15 分钟才点头，
# 超窗口的是家长的手速，不是孩子 —— 拿核销时刻去判等于罚孩子。硬停止时间
# 仍按「此刻」判，那条闸门的全部意义就是拦住「批得太晚」。
#
# 加时申请是唯一的例外通道，放宽的是「这一轮的张数上限」，一条加时抵一轮；
# 硬停止时间不给过 —— 加时能突破的是「今天还想多玩一会儿」，
# 不能突破「今天已经该睡了」。理由落在红线第二条：不碰安全与健康。
FUN_CODE = "ticket_fun"
EXEMPT_CODE = "ticket_exempt"


def _exempt_problem(member_id, note, day=None):
    """豁免券的边界（第 05 章）。

    它只对「额外家务」有效。每日七维度里的「匠力」本来就是这个孩子
    今天该做的事，免掉它等于把豁免券变成一张免打卡券，直接踩红线；
    个人卫生同理，那是安全与健康那条线。另外同一项家务连续两周各免一次
    也不行 —— 那说明的不是孩子偷懒，是这项家务本来就分得不合适。
    """
    note = (note or "").strip()
    if not note:
        return "豁免券要写清免的是哪一项家务，不然没人知道免掉了什么"
    for d in dimensions(day_mode(day or today())):
        if d["name"] and d["name"] in note:
            return "「%s」是每天固定 7 分里的一项，豁免券免不了它" % d["name"]
    for w in ("卫生", "洗澡", "刷牙", "洗漱", "睡觉", "吃饭"):
        if w in note:
            return "个人卫生与作息不能免，这一条是红线"
    it = item_by_code(EXEMPT_CODE)
    if not it:
        return ""
    since = fmt(parse_day(day or today()) - timedelta(days=13))
    dup = db.query_one(
        "SELECT id FROM ticket_request WHERE member_id=? AND item_id=? AND note=?"
        " AND day>=? AND status IN ('approved','self')", (member_id, it["id"], note, since))
    if dup:
        return "同一项家务两周内只能免一次。连着两周都要免，该谈的是这项家务怎么分"
    return ""


def member_name_of(member_id):
    r = db.query_one("SELECT name FROM member WHERE id=?", (member_id,))
    return r["name"] if r else "孩子"


def is_weekend(day):
    """周六、周日算周末。是否假期另外走 day_mode()。"""
    return parse_day(day).weekday() >= 5


def _hhmm(text, fallback=0):
    try:
        h, m = str(text).strip().split(":")
        v = int(h) * 60 + int(m)
        return v if 0 <= v <= 24 * 60 else fallback
    except (ValueError, AttributeError, TypeError):
        return fallback


def _hm_text(v):
    return "%02d:%02d" % (int(v) // 60, int(v) % 60)


def _ts_min(ts):
    """'YYYY-MM-DD HH:MM:SS' → 当天第几分钟。"""
    return _hhmm(ts[11:16]) if ts and len(ts) >= 16 else 0


def _plus_minutes(ts, minutes):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=float(minutes or 0))
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _minutes_between(a, b):
    """b 比 a 晚多少分钟。任一为空返回 None —— 「不知道」和「零分钟」是两件事。"""
    if not a or not b:
        return None
    try:
        return round((datetime.strptime(b, "%Y-%m-%d %H:%M:%S")
                      - datetime.strptime(a, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        return None


def curfew_of(day, member_id=None):
    """这天的硬停止时间（当天第几分钟）。上学日和周末/假期分开。

    晚睡卡在这里加进去：它是唯一一张能把这条线往后挪的卡，
    而且给孩子之前就已经限定了 30 分钟额度，红线（不碰安全与健康）
    仍然成立 —— 挪动的是家长自己设的那条线，不是孩子的睡眠。
    """
    relaxed = day_mode(day) == "holiday" or is_weekend(day)
    key, dflt = ("ticket.curfew_weekend", "22:00") if relaxed else ("ticket.curfew_school", "21:30")
    base = _hhmm(db.cfg(key, dflt), _hhmm(dflt))
    if member_id:
        base += card_flag_minutes(member_id, "late_bed", day)
    return base


def curfew_text(day):
    return _hm_text(curfew_of(day))


def _study_dim(day):
    for d in dimensions(day_mode(day)):
        if d["code"] == "study":
            return d
    return {"name": "智识", "code": "study"}


def study_done(member_id, day):
    """当天「学习任务已完成」没有。

    判定源就是家长每天打的那个智识分（假期自动改名「计划执行」）。
    规则书里两边共用同一个定义，就是为了避免出现
    「打卡说完成了、核销说没完成」这种各说各话。
    没打分也算没过 —— 没有记录就没法证明做完了，顺便也提醒家长去打分。
    """
    r = db.query_one(
        "SELECT COALESCE(SUM(se.value),0) v, COUNT(*) n FROM score_entry se"
        " JOIN dimension dm ON dm.id=se.dimension_id"
        " WHERE se.member_id=? AND se.day=? AND dm.code='study' AND se.voided=0",
        (member_id, day))
    if not r or not r["n"]:
        return False, "今天还没打分"
    if float(r["v"]) <= 0:
        return False, "今天的「%s」没做到" % _study_dim(day)["name"]
    return True, ""


def _ticket_window_minutes():
    """一轮之内，两张券之间允许的空档。超过它就算这一轮断了。

    它同时是「能续多久」和「多久算断」的同一个数，也必须是同一件事：
    分成两个旋钮就会出现「能续却不算同一轮」这种自相矛盾的配置。
    """
    return int(db.cfg("ticket.renew_within_minutes", 10))


def _day_ticket_stats(member_id, item_id, day, exclude_request=None):
    """当天这张券的用量，以及「当前这一轮」串到哪了。

    total / evening / last_end 是全天口径（界面上那句「今天已用」）；
    round_* 是当前这一轮的口径，闸门看的是它。

    「轮」不落库，每次从当天的核销记录里现串 —— 它是一段由时间定义的
    关系，不是一个需要维护的状态。跟 v27 那条「能从时间算出的状态一律
    不落库」同一个口径，也省掉了「谁在什么时候把轮清零」这类问题。

    exclude_request：校验某条挂着待批的申请时，把它从已占张数里扣掉，
    否则它会把自己算成「已经用掉一张」而永远过不了自己的额度闸门。
    """
    X = _ticket_window_minutes()
    evening_from = _hhmm(db.cfg("ticket.evening_after", "20:30"), 20 * 60 + 30)
    rows = db.query(
        "SELECT id, qty, ts, start_at, end_at FROM ticket_request"
        " WHERE member_id=? AND item_id=? AND day=? AND status IN ('approved','self')"
        " ORDER BY COALESCE(start_at, ts), id", (member_id, item_id, day))
    pend = db.query(
        "SELECT id, qty FROM ticket_request"
        " WHERE member_id=? AND item_id=? AND day=? AND status='pending'"
        " ORDER BY ts, id", (member_id, item_id, day))

    total, night, last_end = 0.0, 0.0, None
    for r in rows:
        q = float(r["qty"] or 0)
        total += q
        if r["start_at"] and _ts_min(r["start_at"]) >= evening_from:
            night += q
        if r["end_at"] and (last_end is None or r["end_at"] > last_end):
            last_end = r["end_at"]

    # 从最后一条往前串出「当前这一轮」：相邻两张之间，后一张的提交时刻
    # 距前一张的 end_at 不超过 X 分钟就连上。提前提交算 0 分钟，同样连上。
    cur = []
    for r in reversed(rows):
        if cur:
            gap = _minutes_between(r["end_at"], cur[0]["ts"])
            if gap is None or gap > X:
                break
        cur.insert(0, r)

    pend_qty = sum(float(p["qty"] or 0) for p in pend
                   if not (exclude_request and p["id"] == exclude_request))
    used = sum(float(r["qty"] or 0) for r in cur)

    return {
        "total": total, "evening": night, "last_end": last_end,
        "round_used": used, "round_pending": pend_qty,
        "round_occupy": used + pend_qty,
        "round_start": cur[0]["start_at"] if cur else None,
        "round_end": cur[-1]["end_at"] if cur else None,
        "evening_from": evening_from, "window": X,
    }


def weekend_double_on(day):
    """周末快乐翻倍这一天生效没有。

    开关默认关；开了也只认周六周日，不认假期（写的是「周末」）。
    判定只写这一处，面值计算和界面提示都调它，免得两处各判一次、
    哪天改了口径只改掉一半。
    """
    return bool(day and is_weekend(day) and db.cfg("ticket.weekend_double", False))


def ticket_minutes(item, day=None):
    """一张券换多少分钟。娱乐券以设置为准。

    item.effect_json 里的 minutes 只是建库那一刻的初始值。家长在设置页把
    「娱乐券面值」改掉之后，如果还从 effect_json 读，就成了「设置改了、实际没变」——
    一个会骗人的设置项，比没有这个设置项更糟。

    day 是「这一天用」的意思，不是「这张券哪天的」。周末快乐翻倍只认周六周日，
    所以同一张券在周五值 30 分钟、周六值 60 分钟。判定压在这一个函数里，
    是为了让三条读面值的地方（能不能用的快照、发起核销、手上的券列表）
    永远说同一个数 —— 分开算的话，孩子会看到「列表写 60、用的时候按 30 扣」。

    假期不翻倍：写的是「周末快乐翻倍」，假期是另一件事，别顺手带上。
    day 为 None 表示没有具体哪天（老调用点），按不翻倍处理。
    """
    if not item:
        return 0.0
    if item["code"] == FUN_CODE:
        base = float(db.cfg("ticket.entertainment_minutes", 30) or 30)
        return base * 2 if weekend_double_on(day) else base
    return float(json.loads(item["effect_json"] or "{}").get("minutes", 0) or 0)


def ticket_use_state(member_id, item=None, day=None, at=None, submit_at=None,
                     exclude_request=None):
    """娱乐券此刻能不能用的完整快照，够前端把「为什么不能用」画清楚。

    `at` 是「现在几点」，时段与硬停止按它判；`submit_at` 是「这张券什么
    时候提的」，续费窗口按它判，默认就等于 at。两个分开是给家长侧的二次
    预检用的：孩子 19:30 提的、家长 19:50 才点，超窗口的是家长的手速。

    额度一轮一轮地算：白天一轮 3 张、晚间一轮 2 张，一轮之内可以一张一张
    续。`round_open` 为真表示此刻正处在某一轮的续费窗口里，这时候不论
    上一张刚结束多久，都不该有冷却。
    """
    day = day or today()
    item = item if item is not None else item_by_code(FUN_CODE)
    per = ticket_minutes(item, day)
    single = int(db.cfg("ticket.single_max", 3))
    evening_max = int(db.cfg("ticket.evening_max", 2))
    cooldown = int(db.cfg("ticket.cooldown_minutes", 60))
    evening_from = _hhmm(db.cfg("ticket.evening_after", "20:30"), 20 * 60 + 30)
    window = _ticket_window_minutes()
    blank = {"total": 0.0, "evening": 0.0, "last_end": None, "round_used": 0.0,
             "round_pending": 0.0, "round_occupy": 0.0, "round_start": None,
             "round_end": None, "evening_from": evening_from, "window": window}
    st = _day_ticket_stats(member_id, item["id"], day, exclude_request) if item else blank
    now_min = _ts_min(at) if at else _ts_min(now())
    win_ts = submit_at or at or now()
    curfew = curfew_of(day, member_id)

    # 加时是唯一能放宽额度的通道：一条抵一轮，给这一轮多加 1 张；
    # 不放宽硬停止时间（加时能突破的是「今天还想多玩一会儿」，
    # 不能突破「今天已经该睡了」）。
    extra = 1 if overtime_credit(member_id, day)["count"] else 0

    # 这一轮落在白天还是晚间，由**首张开始的时刻**定，中途不改。还没开轮
    # 就按此刻定。跨过晚间起点的一轮不会半路把额度从 3 变成 2 —— 那样
    # 第 3 张算不算就说不清了。
    evening_on = now_min >= evening_from
    round_night = (_ts_min(st["round_start"]) >= evening_from
                   if st["round_start"] is not None else evening_on)
    cap_round = (evening_max if round_night else single) + extra
    cap_new = (evening_max if evening_on else single) + extra

    # 这一轮断没断：张数满了，或者超过窗口没续。两条只要沾一条，这一轮
    # 就结束，进入冷却。第二条不能省 —— 少了它，孩子每张之间歇 11 分钟
    # 慢慢用，一天下来永远攒不到 3 张，冷却形同虚设。
    occupy = st["round_occupy"]
    full = st["round_start"] is not None and occupy >= cap_round
    gap = _minutes_between(st["round_end"], win_ts) if st["round_end"] else None
    in_window = gap is not None and gap <= window
    round_open = st["round_start"] is not None and not full and in_window

    # 冷却从这一轮最后一张结束那刻起算，不是从当天第一次用券起算 ——
    # 后者会白送孩子一段时间。
    ready = None
    if st["round_end"] and (full or (st["round_start"] is not None and not in_window)):
        ready = _ts_min(st["round_end"]) + cooldown
    cool_left = max(0, ready - now_min) if ready is not None else 0

    # 欠账（校准扣掉的分钟）先从今天的额度里扣，扣不动的那部分继续挂着，
    # 到周期结算再按「固定分达标就清零」处理。这是「券允许负库存」那一条的落点。
    debt = minutes_debt(member_id, day)
    # 今天额外拿到过的分钟额度（加时卡、箱子开出的加时 60 分钟）。
    # 欠着的时候这一项是 0：多出来的时间先拿去还账，不能既免罚又多玩。
    bonus = minutes_credit(member_id, day)
    # 提前提交时新一张要排在上一张后面，所以「离收工还有多久」得从实际
    # 的开始时刻起算，不是从现在起。
    start_probe = max(now_min, _ts_min(st["round_end"])) if round_open else now_min
    room = max(0, curfew - start_probe - debt + bonus)
    by_curfew = int(room // per) if per else cap_new

    # 免等卡免的是「一轮结束后的休息」，不是前置。免掉之后立刻能开新一轮。
    skip = bool(card_flag(member_id, "skip_cooldown", day))
    if skip:
        cool_left, ready = 0, None

    # 这一轮还剩几张。没开轮、或者冷却已经过了，按新一轮算。
    if round_open:
        round_left = max(0, int(cap_round - occupy))
    elif cool_left <= 0:
        round_left = cap_new
    else:
        round_left = 0
    max_qty = max(0, min(round_left, int(by_curfew)))

    return {
        "day": day, "item_id": item["id"] if item else None, "minutes": per,
        "now": _hm_text(now_min), "evening_from": _hm_text(evening_from),
        "curfew": _hm_text(curfew),
        "relaxed": day_mode(day) == "holiday" or is_weekend(day),
        # 今天面值是不是翻倍了。界面据这句说清楚「为什么一张券能换 60 分钟」，
        # 不然孩子会以为是系统算错了。
        "weekend_double": weekend_double_on(day) and bool(item and item["code"] == FUN_CODE),
        "single_max": single, "evening_max": evening_max,
        "cooldown_minutes": cooldown, "renew_within_minutes": window,
        "used_total": st["total"], "used_evening": st["evening"],
        "evening_on": evening_on,
        # 一轮的读数。「这一轮」和「新一轮」在冷却前后是两回事，所以
        # round_cap 跟着冷却走：冷却中显示的是下一次能拿几张。
        "round_cap": (cap_new if (st["round_start"] is None or cool_left > 0
                                  or not round_open) else cap_round),
        "round_used": int(occupy) if st["round_start"] is not None else 0,
        "round_left": round_left, "round_open": round_open,
        "round_night": round_night if round_open else evening_on,
        "round_end": st["round_end"],
        "window_left": (max(0, int(window - (gap or 0))) if round_open else 0),
        "cooldown_left": cool_left, "skip_cooldown": skip,
        "ready_at": _hm_text(ready) if ready is not None else None,
        "last_end": st["last_end"], "overtime_extra": extra, "by_curfew": by_curfew,
        "debt_minutes": debt, "bonus_minutes": bonus,
        "max_qty_now": max_qty,
        "flags": card_flags(member_id, day), "armed": armed_cards(member_id),
        "can_now": bool(cool_left == 0 and max_qty > 0),
        "balance": item_balance(member_id, item["id"]) if item else 0,
    }


def overtime_credit(member_id, day):
    """当天还没用掉的、已批准的加时。

    加时是唯一能突破「一轮张数上限」的通道：一条加时抵一轮，默认 30 分钟
    正好等于一张娱乐券的面值，所以实现上就是「这一轮多给一张」。
    硬停止时间不在可绕范围内。
    """
    rows = db.query("SELECT id FROM overtime_request WHERE member_id=? AND day=?"
                    " AND status='approved' AND consumed_by IS NULL", (member_id, day))
    return {"count": len(rows), "ids": [r["id"] for r in rows]}


def _needs_overtime(member_id, item_id, qty, day, at=None, request_id=None):
    """这一轮是不是靠加时才过得了的。用来记账，让一条加时只抵一轮。

    判据就是这一轮的总张数：超过「不带加时的上限」就是靠它过的。
    """
    item = db.query_one("SELECT * FROM item WHERE id=?", (item_id,))
    st = ticket_use_state(member_id, item, day, at, exclude_request=request_id)
    if not st["overtime_extra"]:
        return False
    no_extra = st["round_cap"] - st["overtime_extra"]
    return st["round_used"] + qty > no_extra or qty > st["by_curfew"]


def ticket_gate(member_id, item_id, qty=1, day=None, at=None, submit_at=None,
                request_id=None):
    """娱乐券的机器闸门，依次判。返回 {ok, code, msg, state}。

    顺序是有讲究的：先报「换个数量也解决不了」的那道（要不要等休息），
    再报数量相关的（这一轮的张数、硬停止），这样孩子拿到的提示是可操作的。

    v23 撤掉了原来排第一的「学习前置」。系统判断不了学习做完没有 ——
    那件事归家长审核，机器只管它算得清的：用多久、隔多久。
    """
    day = day or today()
    item = db.query_one("SELECT * FROM item WHERE id=?", (item_id,))
    if not item:
        return {"ok": False, "code": "noitem", "msg": "没有这张券", "state": None}
    st = ticket_use_state(member_id, item, day, at, submit_at, request_id)
    qty = float(qty or 1)

    if item["code"] != FUN_CODE:
        # 其余五种券消耗的是家长的配合，家长不在场本来就兑不了，
        # 不需要再叠一层机器闸门，走申请让家长点头就够了。
        return {"ok": True, "code": "ok", "msg": "", "state": st}

    if qty <= 0:
        return {"ok": False, "code": "qty", "msg": "至少要 1 张", "state": st}
    if st["balance"] < qty:
        return {"ok": False, "code": "stock",
                "msg": "券不够了（还有 %g 张）" % st["balance"], "state": st}

    # 1 休息：这一轮用满、或者超过窗口没续，就得等。等一会儿就好，和要几张
    #   无关，所以排在数量前面。
    if st["cooldown_left"] > 0:
        return {"ok": False, "code": "cooldown",
                "msg": "这一轮结束了，还要等 %d 分钟（%s 之后能开新一轮）"
                       % (st["cooldown_left"], st["ready_at"]), "state": st}

    # 2 这一轮的张数：白天 3 张、晚间 2 张，加时各 +1。已经用掉的算进去，
    #   排队等批的申请也算 —— 不然几条申请一起挂着，家长全点了就是一轮六张。
    if qty > st["round_left"]:
        if st["round_night"]:
            return {"ok": False, "code": "evening",
                    "msg": "%s 之后开始的一轮最多 %d 张，这一轮已经用了 %d 张"
                           % (st["evening_from"], st["round_cap"], st["round_used"]),
                    "state": st}
        return {"ok": False, "code": "single",
                "msg": "一轮最多 %d 张，这一轮已经用了 %d 张"
                       % (st["round_cap"], st["round_used"]), "state": st}

    # 3 硬停止时间：结束时间不能越过它。加时也绕不过
    if qty > st["by_curfew"]:
        if st["by_curfew"] <= 0:
            return {"ok": False, "code": "curfew",
                    "msg": "到点了，%s 收工，今天先睡" % st["curfew"], "state": st}
        return {"ok": False, "code": "curfew",
                "msg": "接下来只够 %d 张了，再多就超过 %s"
                       % (st["by_curfew"], st["curfew"]), "state": st}

    return {"ok": True, "code": "ok", "msg": "", "state": st}


def expire_ticket_requests(when=None):
    """惰性过期：家长一直没理的申请自动作废，不让孩子无限期干等。"""
    when = when or now()
    rows = db.query("SELECT id FROM ticket_request WHERE status='pending'"
                    " AND expire_at IS NOT NULL AND expire_at<=?", (when,))
    for r in rows:
        db.execute("UPDATE ticket_request SET status='expired', resolved_at=? WHERE id=?",
                   (when, r["id"]))
    return len(rows)


def _settle_ticket_request(request_id, operator_id=None):
    """真正扣券，并把这一轮记成已用（start_at / end_at）。

    开始时刻不一定是「点头那一刻」：孩子提前提交时上一张可能还在放，
    直接从现在开始计时就会和上一张叠在一起。所以接在上一张结束之后。
    """
    r = db.query_one("SELECT * FROM ticket_request WHERE id=?", (request_id,))
    if not r:
        return {"ok": False, "msg": "申请不存在"}
    it = db.query_one("SELECT * FROM item WHERE id=?", (r["item_id"],))
    name = it["name"] if it else "券"
    # 靠加时才过得去的这一轮，把那条加时标记掉，一条只抵一轮
    if _needs_overtime(r["member_id"], r["item_id"], r["qty"], r["day"],
                       request_id=request_id):
        ot = overtime_credit(r["member_id"], r["day"])
        if ot["ids"]:
            db.execute("UPDATE overtime_request SET consumed_by=? WHERE id=?",
                       (request_id, ot["ids"][0]))
    rc = consume_item(r["member_id"], r["item_id"], r["qty"],
                      note="%s ×%g" % (name, r["qty"]), kind="ticket_use",
                      operator_id=operator_id or r["member_id"])
    if rc < 0:
        return {"ok": False, "msg": "券不够了，核销没成"}
    start = now()
    # 排队：这一轮还没放完就接着上一张的结束时刻起算。
    #
    # 这里**不能**再走按天过滤的 _day_ticket_stats。跨零点那一段最典型：
    # 23:50 那张 30 分钟的放到 00:20，孩子在 00:10 续（新申请的 day 已经是
    # 第二天），按「今天」查根本查不到上一张 → round_end 是 None → 从此刻
    # 00:10 起算，跟上一张重叠，整段还少算 10 分钟。
    # 所以按「人 + 券」取最近一次的结束时刻，不带 day 条件。
    # 只用 end_at 真的还没到的那些（过去的自然小于 start，条件自己就挡住了），
    # 一天的额度、能续几张仍由 ticket_gate 管，这里只管接在哪一刻。
    prev = db.query_one(
        "SELECT MAX(end_at) AS last_end FROM ticket_request"
        " WHERE member_id=? AND item_id=? AND id<>? AND end_at IS NOT NULL"
        " AND status IN ('approved','self')",
        (r["member_id"], r["item_id"], request_id))
    if prev and prev["last_end"] and prev["last_end"] > start:
        start = prev["last_end"]
    end = _plus_minutes(start, r["minutes"]) if r["minutes"] else start
    status = "approved" if operator_id else "self"
    db.execute("UPDATE ticket_request SET status=?, operator_id=?, resolved_at=?,"
               " start_at=?, end_at=? WHERE id=?", (status, operator_id, start, start, end, request_id))
    return {"ok": True, "status": status, "start_at": start, "end_at": end,
            "minutes": r["minutes"], "qty": r["qty"], "item": name}


def request_ticket(member_id, item_id, qty=1, note=""):
    """孩子发起一次券核销。

    ticket.need_approval 关掉的话，过完闸门当场核销（家长只在流水里看到）；
    开着的时候生成一条待办推给家长。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    item = db.query_one("SELECT * FROM item WHERE id=?", (item_id,))
    if not item:
        return {"ok": False, "msg": "没有这张券"}
    if item["category"] != "ticket":
        return {"ok": False, "msg": "这张不是券"}
    qty = float(qty or 1)
    day = today()
    if item["code"] == EXEMPT_CODE:
        bad = _exempt_problem(member_id, note, day)
        if bad:
            return {"ok": False, "code": "exempt", "msg": bad}
    expire_ticket_requests()

    g = ticket_gate(member_id, item_id, qty, day)
    if not g["ok"]:
        return {"ok": False, "code": g["code"], "msg": g["msg"], "state": g["state"]}

    dup = db.query_one("SELECT id FROM ticket_request WHERE member_id=? AND item_id=?"
                       " AND status='pending'", (member_id, item_id))
    if dup:
        return {"ok": False, "code": "dup", "msg": "已经有一条在等了，等爸爸妈妈点一下",
                "state": g["state"]}

    if not db.cfg("ticket.need_approval", True):
        rid = db.execute(
            "INSERT INTO ticket_request (member_id, item_id, qty, day, minutes, status, gate,"
            " note, ts) VALUES (?,?,?,?,?,'pending',?,?,?)",
            (member_id, item_id, qty, day, qty * float(g["state"]["minutes"] or 0),
             json.dumps(g["state"], ensure_ascii=False), note, now()))
        out = _settle_ticket_request(rid)
        out["mode"] = "done"
        out["state"] = ticket_use_state(member_id, item, day)
        return out

    ttl = int(db.cfg("ticket.request_ttl_minutes", 20))
    rid = db.execute(
        "INSERT INTO ticket_request (member_id, item_id, qty, day, minutes, status, gate,"
        " note, ts, expire_at) VALUES (?,?,?,?,?,'pending',?,?,?,?)",
        (member_id, item_id, qty, day, qty * float(g["state"]["minutes"] or 0),
         json.dumps(g["state"], ensure_ascii=False), note, now(), _plus_minutes(now(), ttl)))
    push_notify(None, "ticket", "有券要用",
                "%s 想用 %s ×%g%s" % (member_name_of(member_id), item["name"], qty,
                                    ("（%s）" % note) if note else ""))
    return {"ok": True, "mode": "pending", "request_id": rid, "ttl_minutes": ttl,
            "state": g["state"], "msg": "已经告诉爸爸妈妈了，等他们点一下"}


def resolve_ticket_request(request_id, approve, operator_id=None, reject_note=""):
    """家长处理券核销申请。同意前再判一次闸门 —— 从申请到点头之间可能已经过点了。

    二次预检用两个时钟：续费窗口按**提交时刻**判（孩子 19:30 提的、家长
    19:50 才点，超窗口的是家长的手速，不该算在孩子头上）；时段与硬停止按
    **此刻**判 —— 后者这条闸门的全部意义就是拦住「批得太晚」。
    """
    if not is_judge(operator_id):
        return {"ok": False, "msg": "只有爸爸妈妈能处理申请"}
    expire_ticket_requests()
    r = db.query_one("SELECT * FROM ticket_request WHERE id=?", (request_id,))
    if not r:
        return {"ok": False, "msg": "申请不存在"}
    if r["status"] != "pending":
        return {"ok": False, "msg": "这条已经处理过了"}
    if not approve and not (reject_note or "").strip():
        return {"ok": False, "msg": "拒绝要写理由，而且孩子能看到"}
    if not approve:
        db.execute("UPDATE ticket_request SET status='rejected', reject_note=?, operator_id=?,"
                   " resolved_at=? WHERE id=?", (reject_note, operator_id, now(), request_id))
        push_notify(r["member_id"], "ticket", "这次没同意", reject_note)
        return {"ok": True, "approved": False}

    g = ticket_gate(r["member_id"], r["item_id"], r["qty"], r["day"],
                    submit_at=r["ts"], request_id=r["id"])
    if not g["ok"]:
        # 二次预检没过：替家长自动拒掉，并写明是哪一道闸门
        db.execute("UPDATE ticket_request SET status='rejected', reject_note=?, operator_id=?,"
                   " resolved_at=? WHERE id=?",
                   ("（自动）现在已经用不了了：" + g["msg"], operator_id, now(), request_id))
        push_notify(r["member_id"], "ticket", "这次没用上", g["msg"])
        return {"ok": False, "code": g["code"], "msg": "现在已经过不了闸门了：" + g["msg"]}

    out = _settle_ticket_request(request_id, operator_id=operator_id)
    if not out.get("ok"):
        return out
    tail = ("，%s 前用完" % out["end_at"][11:16]) if out.get("minutes") else ""
    push_notify(r["member_id"], "ticket", "券可以用啦",
                "%s ×%g%s" % (out["item"], out["qty"], tail))
    return {"ok": True, "approved": True, "used": out}


def ticket_pending_list(day=None):
    """家长侧待处理列表。每条都带上「现在批了还能不能用」，省得批完才发现过点了。"""
    expire_ticket_requests()
    out = []
    for r in db.query(
            "SELECT tr.*, i.name AS item_name, i.code AS item_code, i.icon, m.name AS who"
            " FROM ticket_request tr JOIN item i ON i.id=tr.item_id"
            " JOIN member m ON m.id=tr.member_id"
            " WHERE tr.status='pending' ORDER BY tr.ts"):
        g = ticket_gate(r["member_id"], r["item_id"], r["qty"], r["day"],
                        submit_at=r["ts"], request_id=r["id"])
        out.append({"id": r["id"], "member_id": r["member_id"], "who": r["who"],
                    "item": r["item_name"], "code": r["item_code"], "icon": r["icon"],
                    "qty": r["qty"], "minutes": r["minutes"], "day": r["day"],
                    "note": r["note"], "ts": r["ts"], "expire_at": r["expire_at"],
                    "can_now": g["ok"], "block_reason": g["msg"]})
    return out


def my_ticket_list(member_id, day=None):
    """孩子侧：今天的申请和结果，含被拒的理由。

    除了当天，还把「已经批了、现在还在玩」的那条一起带出来。22:10 批的
    30 分钟跨过零点就在「今天」这一栏里消失了，孩子会以为时间被吞了 ——
    等它真的结束（end_at 过点）才自然从列表里退出当天这一栏。
    """
    expire_ticket_requests()
    day = day or today()
    now_ts = now()
    raw = db.query(
        "SELECT tr.*, i.name AS item_name, i.icon, om.name AS by_name,"
        " om.role AS by_role FROM ticket_request tr"
        " JOIN item i ON i.id=tr.item_id"
        " LEFT JOIN member om ON om.id=tr.operator_id"
        " WHERE tr.member_id=? AND (tr.day=?"
        "   OR (tr.status IN ('approved','self') AND tr.end_at IS NOT NULL AND tr.end_at>?))"
        " ORDER BY tr.ts", (member_id, day, now_ts))
    # 此刻正在放的那一段（可能由好几张连着续出来的）。列表沿用和「正在玩」
    # 胶囊同一个口径：整段只让打头那张说「正在玩」，后面排队的标 queued，
    # 否则两张卡各自倒数一个不同的数，孩子不知道该看哪个。
    seg = _ticket_segment([r for r in raw
                           if r["status"] in ("approved", "self") and r["end_at"]], now_ts)
    out = []
    for r in raw:
        if seg and r["id"] in seg["ids"] and r["id"] == seg["head"]["id"]:
            # 打头的那张替整段说话：时刻、张数、分钟都按整段报，跟胶囊一个口径
            running, queued = True, False
            end_at = seg["end"]
            total = _minutes_between(seg["start"], seg["end"])
            left = _minutes_between(now_ts, seg["end"])
            qty = sum(float(x["qty"] or 0) for x in seg["part"])
        elif seg and r["id"] in seg["ids"]:
            # 排在它后面的那张：还没开场，只标 queued，读数保持它自己的
            running, queued = False, True
            end_at = r["end_at"]
            total = _minutes_between(r["start_at"], r["end_at"])
            left = _minutes_between(now_ts, r["end_at"])
            qty = float(r["qty"] or 0)
        else:
            running, queued = False, False
            end_at = r["end_at"]
            total = _minutes_between(r["start_at"], r["end_at"])
            left = _minutes_between(now_ts, r["end_at"])
            qty = float(r["qty"] or 0)
        out.append({"id": r["id"], "item": r["item_name"], "icon": r["icon"],
                    "qty": qty, "minutes": r["minutes"], "status": r["status"],
                    "note": r["note"], "reject_note": r["reject_note"],
                    "ts": r["ts"], "expire_at": r["expire_at"],
                    "start_at": r["start_at"], "end_at": end_at, "day": r["day"],
                    # 这两个是「此刻」的答案，不是这张券自己的：running 只有打头
                    # 那张为真，排在其后的只标 queued，分钟已经算进打头那张了。
                    "running": bool(running and left is not None and left > 0),
                    "queued": queued,
                    "left_minutes": left,
                    # 谁批的。闸门全过自动开始的那条没有审批人，写「自动」，
                    # 不写孩子的名字 —— 那条不是他批的，也不是家长批的。
                    "by": r["by_name"] or ("自动" if r["status"] == "self" else ""),
                    "by_role": r["by_role"] or "",
                    "total_minutes": total})
    return out


def ticket_playing(member_id=None):
    """此刻正在玩的人。孩子看自己，家长看全家。

    娱乐券之外那五种券 minutes 是 0，开始就等于结束，永远不会命中 ——
    它们消耗的是家长本人的配合，不存在「还能玩多久」这件事。

    判据是「这个人的娱乐时间此刻还剩多久」，而不是「此刻有没有落在某一张
    券的开始和结束之间」：续券那一张是排在上一张后面开场的，此刻还没开始，
    照后面那种算法它整段不算数，倒计时只会显示上一张那点零头。合并的口径
    见 `_ticket_segment`。

    家长要的是「他现在在不在玩、还有多久」，孩子要的是「我的时间走了多少」，
    问的是同一件事实，所以合成一个函数，谁问都从这儿拿。
    """
    now_ts = now()
    sql = ("SELECT tr.*, i.name AS item_name, i.icon, i.code AS item_code,"
           " m.name AS who, om.name AS by_name FROM ticket_request tr"
           " JOIN item i ON i.id=tr.item_id"
           " JOIN member m ON m.id=tr.member_id"
           " LEFT JOIN member om ON om.id=tr.operator_id"
           " WHERE tr.status IN ('approved','self')"
           " AND tr.end_at IS NOT NULL AND tr.end_at>?")
    args = [now_ts]
    if member_id:
        sql += " AND tr.member_id=?"
        args.append(member_id)
    sql += " ORDER BY COALESCE(tr.start_at, tr.ts), tr.id"
    out = []
    grouped = {}
    for r in db.query(sql, tuple(args)):
        grouped.setdefault(r["member_id"], []).append(r)
    for group in grouped.values():
        seg = _ticket_segment(group, now_ts)
        if seg:
            out.append(_playing_row(seg, now_ts))
    out.sort(key=lambda x: (x["end_at"], x["member_id"]))
    return out


def _ticket_segment(rows, now_ts):
    """把一个成员「正在放的 + 已经排在他后面的」几张串成一段。

    续券那一刻上一张往往还没放完，新的那张开始时刻就落在上一张的结束时刻上，
    此刻它还没开始。要是还按「此刻有没有落在开始和结束之间」算，它就整段不属于
    「正在玩」，倒计时还是显示上一张那点零头 —— 剩 10 分钟的时候续一张，
    屏幕上还在数那 10 分钟，孩子以为白续了。

    所以口径是「这个人的娱乐时间此刻还剩多少」，按时间为轴**往后**串：此刻
    正在放的那段是起点，凡是紧接在这段尾巴后面开场的（开始时刻落在已经串到的
    最晚结束时刻之前或等于它），都算同一段。一次可能续好几张，所以要绕到
    不再有新成员加进来为止。

    串是单向的，两头都得卡住：只收「开始时刻不早于本段头」的行。少了这一头，
    当天更早、**已经玩完**的那张会被吞回整段 —— 它 begin 更小，却一路通过
    `begin <= far`，于是段头被它顶掉、张数和总时长一起撑大。ticket_playing()
    的 SQL 已经滤掉 `end_at <= now`，不会中这一枪；传当天全部行的
    my_ticket_list() 会。

    这么串越不过「一轮结束要休息」那一道：闸门在 ticket_gate 里先判过，
    冷却没走完根本核销不了，也就不会出现「正在休息却还连着算」的记录。

    返回 {ids, part, head, start, end}，没有正在放的就返回 None。
    """
    live = [r for r in rows
            if r["start_at"] and r["end_at"] and r["start_at"] <= now_ts < r["end_at"]]
    if not live:
        return None
    ids = {r["id"] for r in live}
    near = min(r["start_at"] for r in live)
    far = max(r["end_at"] for r in live)
    changed = True
    while changed:
        changed = False
        for r in rows:
            if r["id"] in ids:
                continue
            begin = r["start_at"] or r["ts"]
            if begin and near <= begin <= far:
                ids.add(r["id"])
                if r["end_at"] and r["end_at"] > far:
                    far = r["end_at"]
                changed = True
    part = [r for r in rows if r["id"] in ids]
    head = min(part, key=lambda r: (r["start_at"] or r["ts"], r["id"]))
    return {"ids": ids, "part": part, "head": head,
            "start": head["start_at"], "end": far}


def _playing_row(seg, now_ts):
    """把串好的一段折成外面要的那一条：谁、什么券、几点收工、还剩多久。"""
    part, head = seg["part"], seg["head"]
    first = min(part, key=lambda r: r["id"])
    row = part[-1]
    return {"id": first["id"], "member_id": first["member_id"], "who": first["who"],
            "item": first["item_name"], "code": first["item_code"], "icon": first["icon"],
            "qty": sum(float(r["qty"] or 0) for r in part),
            "note": row["note"],
            "start_at": seg["start"], "end_at": seg["end"],
            "by": first["by_name"] or ("自动" if first["status"] == "self" else ""),
            "total_minutes": _minutes_between(seg["start"], seg["end"]),
            "left_minutes": _minutes_between(now_ts, seg["end"])}


# 保底高级件的抽取顺序：从普通到传说。稀有度高的后抽，
# 「优先给图鉴里还没有的」那条逻辑才不会被低稀有度提前占掉。
RARITY_ORDER = {"common": 0, "rare": 1, "legend": 2, "diamond": 3}


def pick_card(member_id, rarity):
    """抽一张该稀有度的卡，优先给图鉴里还没有的。"""
    cards = db.query("SELECT * FROM item WHERE category='card' AND rarity=? AND active=1", (rarity,))
    if not cards:
        return None
    owned = {r["item_id"] for r in db.query(
        "SELECT DISTINCT item_id FROM holding WHERE member_id=? AND qty>0", (member_id,))}
    fresh = [c for c in cards if c["id"] not in owned]
    return random.choice(fresh or cards)


def pick_candidates(member_id, rarity="common", n=None):
    """自选件的候选：同稀有度里挑 n 张，已经持仓到顶的不出现。

    持有上限是硬的（普通卡 3 张，超了 grant_item 会自动拆成碎片）。系统随机
    给到第 4 张，孩子没感觉；但他自己点选的那张到手瞬间被拆成 1 碎片，他只会
    觉得「我选的东西没了」。自选本来就是把选择权交给他，这个组合反而伤到他，
    所以候选从源头就不让他撞：满了的卡不摆出来，他看到的每一张都真能拿到手。

    「还没有的」排在前面，跟 pick_card 一个取向：这套卡是收集向的。
    """
    n = int(n or seed_data.PICK_OPTION_COUNT)
    cards = db.query("SELECT * FROM item WHERE category='card' AND rarity=? AND active=1"
                     " ORDER BY sort", (rarity,))
    fresh, rest = [], []
    for c in cards:
        have = item_balance(member_id, c["id"])
        cap = c["max_hold"]
        if cap and have + 1e-9 >= cap:
            continue
        (fresh if have <= 0 else rest).append(c)
    random.shuffle(fresh)
    random.shuffle(rest)
    return (fresh + rest)[:max(0, n)]


def _card_brief(c):
    """候选卡发给前端的一小份，够画一张卡面。"""
    return {"code": c["code"], "name": c["name"], "rarity": c["rarity"],
            "card_no": c["card_no"], "desc": c["desc"], "icon": c["icon"]}


def pick_random_from_pool(member_id, tier_row):
    """从随机件池抽一件。抽一件，不是全给。"""
    pool = json.loads(tier_row["random_pool"] or "[]")
    if not pool:
        return None
    pick = random.choice(pool)
    result = dict(pick)
    code = pick.get("code", "")
    qty = pick.get("qty", 1)
    if code == "@common_pick":
        # v38：不预先定好是哪张。开箱时由 pick_candidates 给出几候选，孩子自己挑
        # （qty 是要挑几张，两张必须不同）。以前这里先系统挑一张、打上 pick_required，
        # 而「家长侧指定替换」那个入口全项目从来没有过 —— 孩子拿到的一直是
        # 系统替他挑的那张，代码却当它是「他自己选的」。
        result.update({"resolved_item": None, "pick_required": True, "name": "自选普通卡"})
    elif code == "@common_any":
        card = pick_card(member_id, "common")
        result.update({"resolved_item": card["id"] if card else None, "name": card["name"] if card else "普通卡"})
        result["qty"] = qty
    elif code == "@rare_any":
        card = pick_card(member_id, "rare")
        result.update({"resolved_item": card["id"] if card else None, "name": card["name"] if card else "稀有卡"})
    elif code == "@legend_any":
        card = pick_card(member_id, "legend")
        result.update({"resolved_item": card["id"] if card else None, "name": card["name"] if card else "传说卡"})
    elif pick.get("kind") in ("ticket", "card"):
        it = item_by_code(code)
        result.update({"resolved_item": it["id"] if it else None, "name": it["name"] if it else code})
    else:
        result.update({"name": pick.get("label", code)})
    return result


# ---------------------------------------------------------------------------
# 每日打分
# ---------------------------------------------------------------------------
def day_scores(member_id, day):
    rows = db.query("SELECT * FROM score_entry WHERE member_id=? AND day=? AND voided=0", (member_id, day))
    return {r["dimension_id"]: r for r in rows}


def score_correct_window(member_id, day):
    """这天已经打过的分，还在不在可修正窗口内。返回 (能不能改, 不能改的理由)。

    打分的两个入口（真提交的 submit_day，和打分页只做预览的 _day_view）都要问
    同一个问题。以前这里各写一遍，两处各自读真实时钟，改了一处漏一处看不出来。
    """
    existing = day_scores(member_id, day)
    if not existing:
        return True, ""
    window = int(db.cfg("score.correct_window_hours", 24))
    first = min(r["created_at"] for r in existing.values())
    if datetime.strptime(first, "%Y-%m-%d %H:%M:%S") + timedelta(hours=window) < _dtnow():
        return False, "超过 %d 小时修正窗口" % window
    return True, ""


def score_day_state(member_id, day):
    """打分页这一天站在哪一格。

    界面上四个标签（未打 / 补卡 / 修改 / 超时）和「这一格能不能点」全部只认
    这里返回的一个 state。以前界面拿 scored + can_edit 自己拼，后端 submit_day
    又另有一套限制，于是「界面说能改、点下去被拒」的缝就留在那儿了 ——
    backfill_days 那条从来没进过 can_edit。

    state 的取值：
      future     还没到这天
      transition 假期过渡日，不计分
      settled    这个周期已经结算了
      unscored   今天还没打分，点一项记一项
      backfill   往日欠着，还在那天的次日 12:00 之前，补得上
      modify     打过了，还在 24 小时修正窗口内，得先点「修改」才动得了
      overdue    过了次日 12:00 还是空的（含系统补记的那些），锁死
      locked     打过了但超了修正窗口，或离今天太远补不了，锁死
    """
    if is_transition(day):
        return {"state": "transition", "can_edit": False, "scored": False,
                "auto_filled": False, "reason": "这两天是假期过渡日，不计分"}
    if day > today():
        return {"state": "future", "can_edit": False, "scored": False,
                "auto_filled": False, "reason": "还没到这天"}
    cyc = get_or_create_cycle(member_id, day)
    if cyc and cyc["status"] == "settled":
        return {"state": "settled", "can_edit": False, "scored": False,
                "auto_filled": False, "reason": "这个周期已经结算了"}
    existing = day_scores(member_id, day)
    deadline = _missed_deadline(day)
    base = {"deadline": deadline.strftime("%Y-%m-%d %H:%M")}
    if existing:
        auto = any(str(r["note"] or "") == MISSED_NOTE for r in existing.values())
        if auto:
            return dict(base, state="overdue", can_edit=False, scored=True,
                        auto_filled=True,
                        reason="这天没人打分，系统按满分补记并罚了款，要改只能走家长调整")
        okw, why = score_correct_window(member_id, day)
        return dict(base, state="modify" if okw else "locked", can_edit=okw,
                    scored=True, auto_filled=False,
                    reason="" if okw else why + "，只能走家长调整")
    backfill = int(db.cfg("score.backfill_days", 2))
    if parse_day(day) < parse_day(today()) - timedelta(days=backfill - 1):
        return dict(base, state="locked", can_edit=False, scored=False,
                    auto_filled=False, reason="只能补最近 %d 天的打分" % backfill)
    if _dtnow() > deadline:
        return dict(base, state="overdue", can_edit=False, scored=False,
                    auto_filled=False,
                    reason="过了第二天 12:00，这天已经按满分补记并罚了款，锁死了")
    if day == today():
        return dict(base, state="unscored", can_edit=True, scored=False,
                    auto_filled=False, reason="")
    return dict(base, state="backfill", can_edit=True, scored=False,
                auto_filled=False, reason="")


def submit_day(member_id, day, undone, operator_id=None, note=""):
    """提交某天的打分。undone = 没做到的维度 code 列表；其余按满分记。

    修正窗口内可改，超出窗口拒绝。原始记录不删除，只作废并追加修正流水。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    mode = day_mode(day)
    dims = dimensions(mode)
    if is_transition(day):
        return {"ok": False, "msg": "这两天是假期过渡日，不计分"}
    if day > today():
        return {"ok": False, "msg": "不能给未来打分"}
    backfill = int(db.cfg("score.backfill_days", 2))
    if parse_day(day) < parse_day(today()) - timedelta(days=backfill - 1):
        return {"ok": False, "msg": "只能补最近 %d 天的打分" % backfill}
    if operator_id is None:
        return {"ok": False, "msg": "缺少操作人"}
    if not is_judge(operator_id):
        return {"ok": False, "msg": JUDGE_MSG}

    cycle = get_or_create_cycle(member_id, day)
    if cycle["status"] == "settled":
        return {"ok": False, "msg": "这个周期已经结算，不能再改"}

    existing = day_scores(member_id, day)
    if existing:
        # 系统补记的那一天锁死：它已经过了补打的时点，钱也罚过了。
        # 不加这一条的话，补记刚发生、24 小时修正窗口还开着，家长能把它改掉，
        # 「超时锁死」就只在界面上成立。
        if any(str(r["note"] or "") == MISSED_NOTE for r in existing.values()):
            return {"ok": False, "msg": "这天的分是系统补记的，要改走家长调整"}
        ok, why = score_correct_window(member_id, day)
        if not ok:
            return {"ok": False, "msg": why + "，只能走家长调整"}
    # 「过了次日 12:00」不在这一层拦。那条线是忘打卡兜底管的（ensure_missed_scores
    # 每 5 分钟跑一次，补完就由上面那个 MISSED_NOTE 分支锁住），跟手动补打
    # （score.backfill_days）是两条独立的路 —— 见 v30 那段取舍。这里再拦一次，
    # 等于把两条路拧成一条，测试里「放宽补打窗口好往前补几天」就再也补不进去。
    # 界面那一侧照样锁：score_day_state 给 overdue 的时候 can_edit 是 False。

    undone_set = set(undone or [])
    changed = 0
    for d in dims:
        val = 0.0 if d["code"] in undone_set else float(d["score"])
        row = existing.get(d["id"])
        if row is None:
            db.execute(
                "INSERT INTO score_entry (member_id, cycle_id, day, dimension_id, value, is_fixed,"
                " mode, note, operator_id, created_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
                (member_id, cycle["id"], day, d["id"], val, mode, note, operator_id, now()))
            changed += 1
        elif abs(row["value"] - val) > 1e-9:
            db.execute("UPDATE score_entry SET voided=1 WHERE id=?", (row["id"],))
            db.execute(
                "INSERT INTO score_entry (member_id, cycle_id, day, dimension_id, value, is_fixed,"
                " mode, note, operator_id, created_at, revised_at, revision_count)"
                " VALUES (?,?,?,?,?,1,?,?,?,?,?,?)",
                (member_id, cycle["id"], day, d["id"], val, mode, note, operator_id, now(), now(),
                 (row["revision_count"] or 0) + 1))
            db.execute("INSERT INTO correction (target_type, target_id, before_json, after_json,"
                       " actor_id, ts) VALUES ('score_entry',?,?,?,?,?)",
                       (row["id"], json.dumps({"value": row["value"]}),
                        json.dumps({"value": val}), operator_id, now()))
            changed += 1

    # 差额写流水
    before = cycle["fixed_score"] or 0
    after_cycle = recalc_cycle(cycle["id"])
    diff = (after_cycle["fixed_score"] or 0) - before
    if abs(diff) > 1e-9:
        add_ledger(member_id, "daily_score", cycle_id=cycle["id"], day=day, energy=diff,
                   note="%s 打分调整 %+g 分" % (day, diff), operator_id=operator_id,
                   meta={"undone": sorted(undone_set), "mode": mode})
    # v20：打完分回来问一句「有没有哪条心愿刚够」
    if changed:
        check_wish_ready(member_id)
    return {"ok": True, "changed": changed, "cycle": cycle_snapshot(cycle["id"])}


def day_revision_flag(member_id, day):
    n = db.query_one(
        "SELECT COALESCE(MAX(revision_count),0) v FROM score_entry WHERE member_id=? AND day=?",
        (member_id, day))["v"]
    return n >= int(db.cfg("score.correct_flag_count", 3))


# ---------------------------------------------------------------------------
# 星探时刻（额外加分，增益通道）
# ---------------------------------------------------------------------------
def cap_energy(member_id, cycle, energy):
    """周能量封顶：星探与任务奖励共用每周 7 分。

    7 分恰好等于「多一天」——额外表现最多补回一整天的缺口。超出部分自动转星尘
    （第 01、12 章）。两个入口走同一个函数，是为了不让「星探有上限、任务没有」
    这种缝再出现一次：任务奖励的周能量不封顶的话，宝箱阶梯可以被活动刷穿。

    返回 (真正进周能量的部分, 自动转成的星尘)。
    """
    cap = float(db.cfg("score.explore_weekly_cap", 7))
    used = float(recalc_cycle(cycle["id"])["bonus_energy"] or 0)
    energy = max(0.0, float(energy or 0))
    if energy <= 0:
        return 0.0, 0.0
    if used + energy <= cap + 1e-9:
        return energy, 0.0
    keep = max(0.0, round(cap - used, 2))
    return keep, round(energy - keep, 2)


def add_explore(member_id, day, phrase, kind=None, energy=None, stardust=None,
                dimension_code=None, operator_id=None):
    if not db.cfg("score.explore_enabled", True):
        return {"ok": False, "msg": "星探时刻已关闭"}
    if not (phrase or "").strip():
        return {"ok": False, "msg": "星探时刻必须附一句具体的话"}
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}

    cycle = get_or_create_cycle(member_id, day)
    kind = kind or db.cfg("score.explore_default_kind", "stardust")
    # 三种发放类型的额度
    if kind == "stardust":
        energy, stardust = 0, min(float(stardust or 5), 5)
    elif kind == "energy":
        energy, stardust = min(float(energy or 1), 1), 0
    else:
        energy, stardust = min(float(energy or 1), 1), min(float(stardust or 3), 3)

    # 每日上限
    day_cap = float(db.cfg("score.explore_daily_cap", 2))
    used_today = db.query_one(
        "SELECT COALESCE(SUM(energy),0) v FROM explore WHERE member_id=? AND day=?",
        (member_id, day))["v"]
    if used_today + energy > day_cap:
        energy = max(0.0, day_cap - used_today)

    # 每周上限（与任务奖励共用每周 7 分，超出自动转星尘）
    energy, overflow = cap_energy(member_id, cycle, energy)

    dim_id = None
    if dimension_code:
        d = db.query_one("SELECT id FROM dimension WHERE code=?", (dimension_code,))
        dim_id = d["id"] if d else None

    eid = db.execute(
        "INSERT INTO explore (member_id, cycle_id, day, kind, energy, stardust, phrase, dimension_id,"
        " operator_id, ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (member_id, cycle["id"], day, kind, energy, stardust, phrase, dim_id, operator_id, now()))

    if energy:
        add_ledger(member_id, "explore", cycle_id=cycle["id"], day=day, energy=energy,
                   ref_type="explore", ref_id=eid, note=phrase, operator_id=operator_id)
    # 超出周上限的部分自动转星尘
    if overflow > 0:
        add_ledger(member_id, "explore", cycle_id=cycle["id"], day=day, stardust=overflow,
                   ref_type="explore", ref_id=eid, note="周能量已满，自动转星尘", operator_id=operator_id)
    if stardust:
        sd, doubled_st = stardust, False
        if consume_armed(member_id, "double_reward"):
            sd, doubled_st = stardust * 2, True
        add_ledger(member_id, "explore", cycle_id=cycle["id"], day=day, stardust=sd,
                   ref_type="explore", ref_id=eid, operator_id=operator_id,
                   note=phrase + ("（翻倍卡 ×2）" if doubled_st else ""))

    recalc_cycle(cycle["id"])
    # 星探也可能把周能量顶过某条心愿的门槛
    check_wish_ready(member_id)
    return {"ok": True, "explore_id": eid, "energy": energy, "stardust": stardust,
            "overflow_stardust": overflow}


# ---------------------------------------------------------------------------
# 速率换算与快照
# ---------------------------------------------------------------------------
def tier_for_energy(energy, ratio=1.0, fixed=None):
    """本周该发哪一档。默认按周能量（固定分 + 额外加分）算。

    唯一例外是最高那一档：完美箱要求<b>固定分满 49</b>，不能用额外分凑
    （第 01、03 章）。全勤是整套系统里唯一买不到、也补不出的东西，
    42 分固定分再加 7 分星探就能拿完美箱，这条门槛就没有意义了。
    """
    rows = db.query("SELECT * FROM box_tier ORDER BY tier")
    if not rows:
        return None
    top = rows[-1]["tier"]
    strict = bool(db.cfg("box.perfect_require_fixed_49", True))
    best = None
    for t in rows:
        bar = t["threshold"] * ratio
        if energy + 1e-9 < bar:
            continue
        if strict and fixed is not None and t["tier"] == top and float(fixed or 0) + 1e-9 < bar:
            continue                      # 能量够了，但固定分没满，最高档不给
        best = t
    return best


def next_tier(energy, ratio=1.0):
    for t in db.query("SELECT * FROM box_tier ORDER BY tier"):
        if energy + 1e-9 < t["threshold"] * ratio:
            return t
    return None


def box_tiers_brief():
    """七档的轻量视图，给前端画那条横向阶梯用。

    和 /api/boxes 里的整行不同，这里只要「叫什么、多少分、给几张券几张卡」——
    阶梯是塞在卡片里的一条，把随机池、价签、图标全带上纯属浪费。
    「这周」和「宝箱」两页都用它，门槛就只有一个来源。
    """
    out = []
    for t in db.query("SELECT * FROM box_tier ORDER BY tier"):
        out.append({"tier": t["tier"], "name": t["name"], "threshold": t["threshold"],
                    "tickets": t["tickets"], "stardust": t["stardust"],
                    "card_count": sum(c["count"] for c in box_cards(t))})
    return out


def cycle_snapshot(cycle_id):
    c = recalc_cycle(cycle_id)
    if not c:
        return None
    # 档位按周能量算，但最高档要固定分满 —— 前端画进度条和结算必须同一口径
    t = tier_for_energy(c["energy"], c["threshold_ratio"], c["fixed_score"])
    n = next_tier(c["energy"], c["threshold_ratio"])
    return {
        "id": c["id"], "member_id": c["member_id"],
        "start_date": c["start_date"], "end_date": c["end_date"],
        "fixed_score": c["fixed_score"], "bonus_energy": c["bonus_energy"],
        "energy": c["energy"], "countable_days": c["countable_days"],
        "ratio": c["threshold_ratio"], "status": c["status"],
        # icon 跟着给出去：宝箱页中间那只大箱子按它渲染，家长在「给它们换张图」
        # 里换过的图要能落到这一屏，不然那里改完只有七列跟着变，中间还是老样子。
        "tier": {"tier": t["tier"], "name": t["name"], "threshold": t["threshold"],
                 "icon": t["icon"]} if t else None,
        "next_tier": {"tier": n["tier"], "name": n["name"], "threshold": n["threshold"],
                      "icon": n["icon"],
                      "need": round(n["threshold"] * c["threshold_ratio"] - c["energy"], 2)} if n else None,
        "awarded": c["tier_awarded"], "stardust_grant": c["stardust_grant"],
        "tiers": box_tiers_brief(),
    }


def member_overview(member_id):
    days = int(db.cfg("cycle.length_days", 7))
    cyc = current_cycle(member_id)
    if not cyc:
        # 家长：不在循环里，一切归零，也不建周期
        return {"member_id": member_id, "is_player": False, "stardust": 0, "fragment": 0,
                "cycle": None, "tickets": [], "cards": [], "level": None}
    return {
        "member_id": member_id,
        "is_player": True,
        "stardust": stardust_balance(member_id),
        "fragment": fragment_balance(member_id),
        "cycle": cycle_snapshot(cyc["id"]),
        "tickets": to_ticket_list(member_id),
        "cards": to_card_list(member_id),
        "level": level_of(member_id),
    }


# ---------------------------------------------------------------------------
# 孩子数据总览（v15）
#
# 三层都从现有表聚合，不新建表：
#   总览 —— 每个孩子一张速览卡，一次全拿
#   详细 —— 一个孩子的等级、周期、这七天、手上的东西、在做的事
#   记录 —— 天 × 维度 的明细矩阵，外加各维度达成率
# ---------------------------------------------------------------------------
def _kids():
    return db.query("SELECT * FROM member WHERE active=1 AND role='child' ORDER BY sort")


def _day_snapshot(member_id, day):
    """某一天拿到了多少分、满分多少。没打过分也照样给数，前端好画空格子。"""
    dims = dimensions(day_mode(day))
    rows = day_scores(member_id, day)
    got = round(sum(float(r["value"]) for r in rows.values()), 2)
    full = round(sum(float(d["score"]) for d in dims), 2)
    return {"day": day, "score": got, "full": full, "scored": bool(rows),
            "ratio": round(got / full, 3) if full else 0,
            "transition": is_transition(day), "future": day > today()}


def kids_overview():
    """所有孩子一张速览卡。一次拿全，前端别为每个孩子各发一个请求。"""
    d0 = today()
    out = []
    for m in _kids():
        mid = m["id"]
        tds = _day_snapshot(mid, d0)
        tds["revised"] = day_revision_flag(mid, d0)
        cyc = current_cycle(mid)
        tickets, cards = to_ticket_list(mid), to_card_list(mid)
        doing = db.query_one(
            "SELECT COUNT(*) c FROM task WHERE assignee_id=? AND kind='reward'"
            " AND status IN ('pending','claimed','submitted')", (mid,))["c"]
        doing += db.query_one(
            "SELECT COUNT(*) c FROM help_request WHERE member_id=? AND verified_at IS NULL",
            (mid,))["c"]
        doing += db.query_one("SELECT COUNT(*) c FROM wish WHERE member_id=? AND status='active'",
                              (mid,))["c"]
        out.append({
            "member_id": mid, "name": m["name"], "avatar": m["avatar"],
            "today": tds,
            "cycle": cycle_snapshot(cyc["id"]) if cyc else None,
            "stardust": stardust_balance(mid),
            "debt": debt_balance(mid),
            "fragment": fragment_balance(mid),
            "level": level_of(mid),
            "device": device_downgrade_state(mid),
            # 今天在生效的卡。是 N+1 查询里唯一值得多一次查的那种例外：
            # 家长扫一眼就该知道「这个孩子今天有特例」，而不是等他抗辩。
            "card_flags": card_flags(mid, d0),
            "holdings": {"tickets": sum(t["qty"] for t in tickets),
                         "cards": sum(c["qty"] for c in cards),
                         "fragment": fragment_balance(mid),
                         "ticket_list": tickets, "card_list": cards},
            "doing": doing,
        })
    return out


def kid_detail(member_id, days=None):
    """一个孩子的详细情况。周期、这七天、手上有的、手上在做的。"""
    m = db.query_one("SELECT * FROM member WHERE id=?", (member_id,))
    if not m:
        return None
    d0 = today()
    cyc = current_cycle(member_id)
    week = []
    if cyc:
        d = parse_day(cyc["start_date"])
        end = parse_day(cyc["end_date"])
        while d <= end:
            week.append(_day_snapshot(member_id, fmt(d)))
            d += timedelta(days=1)
    tasks = [dict(r, reward=json.loads(r["reward_json"] or "{}"),
                  reward_text=_reward_text(r["reward_type"], json.loads(r["reward_json"] or "{}")))
             for r in db.query(
        "SELECT * FROM task WHERE assignee_id=? AND kind='reward'"
        " AND status IN ('pending','claimed','submitted') ORDER BY id DESC", (member_id,))]
    helps = [dict(r) for r in db.query(
        "SELECT * FROM help_request WHERE member_id=? AND verified_at IS NULL ORDER BY id DESC",
        (member_id,))]
    wishes = [dict(r) for r in db.query(
        "SELECT * FROM wish WHERE member_id=? AND status='active' ORDER BY id DESC", (member_id,))]
    return {
        "member_id": member_id, "name": m["name"], "avatar": m["avatar"],
        "level": level_of(member_id),
        "stardust": stardust_balance(member_id),
        "debt": debt_balance(member_id),
        "fragment": fragment_balance(member_id),
        "today": _day_snapshot(member_id, d0),
        "cycle": cycle_snapshot(cyc["id"]) if cyc else None,
        "week": week,
        "tickets": to_ticket_list(member_id),
        "cards": to_card_list(member_id),
        "tasks": tasks, "helps": helps, "wishes": wishes,
    }


def score_history(member_id, days=30, until=None):
    """打分记录：一行一天、一列一个维度。拿到的给分值，没拿到的空着。

    维度 id 全校只有一套，假期只是改个名字，所以矩阵的列固定用学校那版名字，
    每格再带上当天的实际叫法。
    """
    end = parse_day(until or today())
    start = end - timedelta(days=max(1, int(days)) - 1)
    rows = db.query(
        "SELECT day, dimension_id, value, note, revision_count FROM score_entry"
        " WHERE member_id=? AND day>=? AND day<=? AND voided=0",
        (member_id, fmt(start), fmt(end)))
    by_day = {}
    for r in rows:
        by_day.setdefault(r["day"], {})[r["dimension_id"]] = r
    ref = dimensions("school")
    items = []
    d = start
    while d <= end:
        ds = fmt(d)
        dims = dimensions(day_mode(ds))
        cell = by_day.get(ds, {})
        cells, got = [], 0.0
        for x in dims:
            r = cell.get(x["id"])
            cells.append({"code": x["code"], "name": x["name"], "base_name": x["base_name"],
                          "icon": x["icon"], "max": x["score"],
                          "value": float(r["value"]) if r else None,
                          "got": bool(r) and (r["value"] or 0) > 0,
                          "note": r["note"] if r else "",
                          "revision_count": (r["revision_count"] or 0) if r else 0})
            got += float(r["value"]) if r else 0.0
        items.append({"day": ds, "mode": day_mode(ds), "cells": cells, "score": round(got, 2),
                      "full": round(sum(float(x["score"]) for x in dims), 2),
                      "scored": bool(cell), "transition": is_transition(ds),
                      "future": ds > today(),
                      "reason": _day_reason(cell)})
        d += timedelta(days=1)
    # 达成率只算真打过分的那些天。没打分的天不代表这项没做到，
    # 把它算进分母只会把比例压得没法看 —— 那是「没记录」，不是「没达成」。
    counted = [it for it in items if it["scored"]]
    agg = []
    for x in ref:
        hit = sum(1 for it in counted
                  for c in it["cells"] if c["code"] == x["code"] and c["got"])
        agg.append({"code": x["code"], "name": x["name"], "icon": x["icon"],
                    "hit": hit, "total": len(counted),
                    "rate": round(hit / len(counted), 3) if counted else 0})
    full = round(sum(it["full"] for it in counted), 2)
    got = round(sum(it["score"] for it in counted), 2)
    return {"member_id": member_id, "start": fmt(start), "end": fmt(end), "days": items,
            "dims": agg, "total": {"score": got, "full": full,
                                   "rate": round(got / full, 3) if full else 0,
                                   "days": len(counted)}}


def _day_reason(cell):
    """这一天为什么不是满分：把没拿到的维度和当天备注捡出来。"""
    lost = [d["name"] for d in dimensions("school") if cell.get(d["id"], None) is not None
            and (cell[d["id"]]["value"] or 0) <= 0]
    notes = [r["note"] for r in cell.values() if r["note"]]
    return {"lost": lost, "note": notes[0] if notes else ""}


# ---------------------------------------------------------------------------
# 首页动态（v18）
#
# 首页第一屏要能回答三个问题：在做什么、做到哪一步、还有什么没完。
# 这三样东西分别躺在 task / wish / calibration 三张表里，结构完全不一样，
# 所以这里先把它们拍平成同一副骨架再交给前端：
#
#   kind / kind_text   这是任务、心愿还是校准
#   state_text         一句话讲清卡在哪一步（前端只画，不下判断）
#   step + steps       任务和修复任务画三颗点：待做 → 在做 → 交上去
#   percent + text     心愿画进度条，算法复用 wish_progress（只有一份）
#
# 全部现算，不落表。落表就得有人记得在每次打分、每次确认之后回来更新它，
# 而这种「谁忘了谁就错」的设计在这套系统里已经吃过一次亏。
#
# rank 是排序权重，越小越靠前。排在最前面的是「球在大人手上」的那些：
# 孩子交了等确认、心愿满了等兑现 —— 停在这儿的东西不会自己往前走。
# ---------------------------------------------------------------------------
FEED_TASK_STEPS = ["待做", "在做", "交上去"]
_FEED_TASK_STEP = {"pending": 1, "claimed": 2, "submitted": 3}
_FEED_TASK_STATE = {"pending": "还没开始", "claimed": "在做", "submitted": "交了，等确认"}
_WISH_COND_LABEL = {"fixed": "固定分达标", "stardust": "星尘自付", "task_count": "完成任务数",
                    "streak": "连续达标", "perfect_day": "完美日",
                    "custom": "说好的一条", "any": "多选条件"}


def _one_cond_text(ctype, cond):
    """一条（不用嵌套的）条件翻成一句短话。"""
    if ctype == "custom":
        # 自定义那条的「条件」就是那句话本身，别再在前面挂一个条件名
        return str((cond or {}).get("text") or "").strip() or _WISH_COND_LABEL["custom"]
    label = _WISH_COND_LABEL.get(ctype, ctype or "")
    n = _cond_target(cond)
    return label if n is None else "%s %g" % (label, n)


def wish_cond_text(w):
    """把心愿的条件翻成一句人话，给动态、通知和报告用。

    前端另有一份同名的实现，因为那条挂起的心愿条件是一段空串，
    得有地方兜住；这里只处理「条件已经定了」的那些。
    """
    if not isinstance(w, dict):     # 行对象也吃，调用点有直接丢 row 过来的
        w = dict(w) if w else {}
    if not w or not w.get("cond_type"):
        return "条件还没定"
    c = w.get("cond") if isinstance(w.get("cond"), dict) else None
    if c is None:
        try:
            c = json.loads(w.get("cond_json") or "{}")
        except (TypeError, ValueError):
            c = {}
    ctype = w["cond_type"]
    if ctype == "custom":
        # 自定义那条的「条件」本身就是那句话，不要把标签叠在它前面念一遍
        return (str(c.get("text") or "").strip()) or _WISH_COND_LABEL["custom"]
    if ctype == "any":
        parts = [p for p in (_one_cond_text(it.get("type"), it)
                             for it in (c.get("items") or []) if isinstance(it, dict)) if p]
        if not parts:
            return _WISH_COND_LABEL["any"]
        n = _any_need(c, len(parts))
        return "、".join(parts) + ("　其中做到一条就算" if n <= 1
                                   else "　其中做到 %d 条就算" % n)
    return _one_cond_text(ctype, c)


def _feed_tasks(member_id=None):
    """还没结束的发布任务。状态就是进度，不需要另算一个百分比。"""
    sql = ("SELECT t.*, m.name AS who FROM task t JOIN member m ON m.id=t.assignee_id"
           " WHERE t.kind='reward' AND t.status IN ('pending','claimed','submitted')")
    args = []
    if member_id:
        sql += " AND t.assignee_id=?"
        args.append(member_id)
    sql += " ORDER BY t.id DESC LIMIT 40"
    out = []
    for r in db.query(sql, args):
        st = r["status"]
        detail = "奖励 " + _reward_text(r["reward_type"], json.loads(r["reward_json"] or "{}"))
        if r["deadline"]:
            detail += "　截止 " + str(r["deadline"])[:16]
        out.append({
            "kind": "task", "kind_text": "任务",
            "task_id": r["id"], "member_id": r["assignee_id"], "who": r["who"],
            "title": r["title"], "std": r["std"],
            "state_key": st, "state_text": _FEED_TASK_STATE.get(st, st),
            "detail": detail, "icon": r["icon"],
            "step": _FEED_TASK_STEP.get(st, 1), "steps": FEED_TASK_STEPS,
            "percent": None, "text": "",
            # 交了等确认的排最前：孩子那头的活已经干完，家长不点它就永远停着
            "rank": 0 if st == "submitted" else (2 if st == "claimed" else 3),
            "ts": r["submitted_at"] or r["claimed_at"] or r["created_at"],
        })
    return out


def _feed_wishes(member_id=None):
    """挂起的和进行中的心愿。进度直接借 wish_progress，前后端只此一份算法。"""
    sql = "SELECT * FROM wish WHERE status IN ('wished','active')"
    args = []
    if member_id:
        sql += " AND member_id=?"
        args.append(member_id)
    sql += " ORDER BY id DESC LIMIT 40"
    out = []
    for r in db.query(sql, args):
        v = wish_view(r, with_progress=True)
        p = v.get("progress") or {}
        ready = bool(p.get("ready"))
        manual = bool(p.get("manual"))
        if r["status"] == "wished":
            detail = "还挂在墙上等定条件，这会儿不占「进行中」的名额"
            state, rank = "等爸爸妈妈定条件", 1
        elif manual:
            # 自定义那条没有进度条，状态也就不该说「进行中」——
            # 系统算不出它在走还是停了，能说的只有「好了就说一声」。
            detail = "条件　「%s」" % (p.get("text") or "")
            state, rank = "好了就说一声", 2
        elif p.get("has_manual"):
            # 多选里含自定义那条：系统能算的那部分照常走，但里面有一条得人判，
            # 所以不能报「进行中」—— 那条走到了哪一步，机器根本不知道。
            detail = ("条件　" + _WISH_COND_LABEL["any"] + "　" + (p.get("text") or ""))
            state, rank = "好了就说一声", 2
        else:
            # 只写条件名，不写门槛数字：数字在下面那条进度里，
            # 两行都写「3」的时候，看的人会以为自己数错了
            detail = "条件　" + _WISH_COND_LABEL.get(r["cond_type"], r["cond_type"] or "还没定")
            state, rank = ("够了，可以兑现" if ready else "进行中"), (0 if ready else 2)
        out.append({
            "kind": "wish", "kind_text": "心愿",
            "wish_id": r["id"], "member_id": r["member_id"],
            "who": member_name_of(r["member_id"]),
            "title": r["title"], "std": "",
            "state_key": "ready" if ready else r["status"], "state_text": state,
            "detail": detail, "icon": r["icon"],
            "step": None, "steps": [],
            "percent": p.get("percent"), "text": p.get("text", ""),
            "rank": rank, "ts": r["created_at"],
        })
    return out


def _feed_calibrations(member_id=None):
    """还没了结的校准：修复任务没交、欠款没结、设备降级还没到期。

    已经当场生效的那几种（扣时长）不在这里 —— 它们没有「还没做完」这一说，
    摆进动态只会变成一条永远挂着的旧账。
    """
    ids = [member_id] if member_id else [m["id"] for m in _kids()]
    if not ids:
        return []
    out = []
    sql = ("SELECT t.*, m.name AS who FROM task t JOIN member m ON m.id=t.assignee_id"
           " WHERE t.kind='repair' AND t.status IN ('pending','claimed','submitted')")
    args = []
    if member_id:
        sql += " AND t.assignee_id=?"
        args.append(member_id)
    sql += " ORDER BY t.id DESC LIMIT 40"
    for r in db.query(sql, args):
        st = r["status"]
        out.append({
            "kind": "calibration", "kind_text": "校准",
            "task_id": r["id"], "member_id": r["assignee_id"], "who": r["who"],
            "title": r["title"], "std": r["std"],
            "state_key": st, "state_text": _FEED_TASK_STATE.get(st, st),
            "detail": "完成标准：" + (r["std"] or "没写"),
            "step": _FEED_TASK_STEP.get(st, 1), "steps": FEED_TASK_STEPS,
            "percent": None, "text": "",
            "rank": 0 if st == "submitted" else 2,
            "ts": r["submitted_at"] or r["created_at"],
        })
    for mid in ids:
        d = debt_balance(mid)
        if d > 0:
            last = db.query_one("SELECT ts FROM ledger WHERE member_id=? AND delta_debt>0 AND voided=0"
                                " ORDER BY id DESC LIMIT 1", (mid,))
            out.append({
                "kind": "calibration", "kind_text": "校准",
                "task_id": None, "member_id": mid, "who": member_name_of(mid),
                "title": "还没结清的欠款", "std": "",
                "state_key": "debt", "state_text": "待结清",
                "detail": "欠 %g 星尘。周期末先从星尘里抵扣，扣不完的滚一期就免掉，不会变成负数" % d,
                "step": None, "steps": [], "percent": None, "text": "",
                "rank": 4, "ts": last["ts"] if last else "",
            })
        for c in db.query("SELECT * FROM calibration WHERE member_id=? AND effect_type='device'"
                          " ORDER BY id DESC LIMIT 10", (mid,)):
            left = (parse_day(c["ts"]) + timedelta(days=3) - parse_day(today())).days
            if left < 0:
                continue
            out.append({
                "kind": "calibration", "kind_text": "校准",
                "task_id": None, "member_id": mid, "who": member_name_of(mid),
                "title": "设备降级中", "std": "",
                "state_key": "device", "state_text": "还剩 %d 天" % left,
                "detail": "设备改到公共区域使用，3 天后自动恢复。" + (c["reason"] or ""),
                "step": None, "steps": [],
                "percent": int(round((3 - left) / 3.0 * 100)), "text": "第 %d / 3 天" % (3 - left),
                "rank": 5, "ts": c["ts"],
            })
    return out


def _feed_recent(member_id=None, limit=6):
    """最近发生的事。首页只有「在做的事」会显得像一张表格，
    加上这一小段才有「这几天家里发生了什么」的感觉。"""
    ids = [member_id] if member_id else [m["id"] for m in _kids()]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    ev = []
    # v28：孩子自己按的那些按钮（买券、买卡、开箱、兑零花钱、用券……）
    # 以前只在账本里躺着，首页看不见，家长会觉得「东西自己长出来的」。
    # 取最近几条混进来，一屏就知道他今天自己做过什么主。
    # 混的时候刻意排在任务前面：时间戳撞成同一秒时（补数据、批量灌的库常见），
    # 稳定排序会留先入列表的那条，排在后面就永远看不见了。
    for g in ("self", "given"):
        for x in activity(member_id, group=g, limit=max(0, int(limit) * 2))["items"]:
            ev.append((x["ts"], g, x["who"],
                       x["text"] + ("　" + x["impact"] if x["impact"] else "")))
    for r in db.query("SELECT * FROM task WHERE assignee_id IN (%s)" % q, ids):
        who = member_name_of(r["assignee_id"])
        if r["claimed_at"]:
            ev.append((r["claimed_at"], "task", who, "领了「%s」" % r["title"]))
        if r["submitted_at"]:
            ev.append((r["submitted_at"], "task", who, "交了「%s」" % r["title"]))
        if r["confirmed_at"] and r["kind"] == "reward":
            ev.append((r["confirmed_at"], "task", who, "做完了「%s」" % r["title"]))
    for r in db.query("SELECT * FROM wish WHERE member_id IN (%s)" % q, ids):
        who = member_name_of(r["member_id"])
        if r["created_at"]:
            ev.append((r["created_at"], "wish", who, "许了个愿：%s" % r["title"]))
        if r["achieved_at"]:
            ev.append((r["achieved_at"], "wish", who, "谈成了一个心愿：%s" % r["title"]))
        if r["cancelled_at"]:
            ev.append((r["cancelled_at"], "wish", who, "收起了「%s」" % r["title"]))
    for r in db.query("SELECT * FROM calibration WHERE member_id IN (%s)" % q, ids):
        ev.append((r["ts"], "calibration", member_name_of(r["member_id"]),
                   "记了一次校准：%s" % r["reason"]))
    names = {t["tier"]: t["name"] for t in db.query("SELECT tier, name FROM box_tier")}
    for r in db.query("SELECT * FROM box_open WHERE member_id IN (%s)" % q, ids):
        ev.append((r["ts"], "box", member_name_of(r["member_id"]),
                   "开了%s" % names.get(r["tier"], "一个宝箱")))
    ev.sort(key=lambda x: x[0] or "", reverse=True)
    return [{"ts": t, "kind": k, "who": w, "text": s} for t, k, w, s in ev[:max(0, int(limit))]]


def feed(member_id=None, limit=12, recent_limit=6):
    """首页动态。家长看全部孩子（每条带名字），孩子只看自己那份。

    member_id 传 None 是「全家」的意思，不是「没指定」——
    这条和别的接口不一样，因为首页本来就该一屏看完几个孩子。
    """
    archive_due_tasks()
    doing = _feed_tasks(member_id) + _feed_wishes(member_id) + _feed_calibrations(member_id)
    # 先按时间倒序，再按 rank 稳定排序：同一档里最新的那条在最上面
    doing.sort(key=lambda x: x.get("ts") or "", reverse=True)
    doing.sort(key=lambda x: x.get("rank", 9))
    n = max(1, int(limit))
    return {"items": doing[:n], "total": len(doing),
            "recent": _feed_recent(member_id, recent_limit),
            "member_id": member_id}


# ---------------------------------------------------------------------------
# 动态日志（v28）：把账本翻成人话
# ---------------------------------------------------------------------------
# 这一节是给家长的一个交代。「孩子的券怎么突然多了一张」这种问题，
# 答案是「券的每一次进出都在账本里」—— 余额本来就是流水求和算出来的，
# 缺的只是把它说成人话。所以这里不另建表、不另记事件：读账本，翻译。
#
# 分四类，家长按类筛。分类看的是「这件事是谁决定的」，
# 不是「这件事对谁有利」：孩子自己按的按钮是一类，家长给的和系统发的是一类。
ACTIVITY_GROUPS = (
    ("self", "孩子自己做的"),
    ("given", "拿到手的"),
    ("judge", "家长给的评价"),
    ("system", "系统结算"),
)
_GROUP_TEXT = dict(ACTIVITY_GROUPS)
_KIND_GROUP = {
    "box_purchase": "self", "shop_ticket": "self", "shop_card": "self",
    "cash_exchange": "self", "ticket_use": "self", "card_use": "self",
    "card_effect": "self", "renew": "self", "pool_deposit": "self",
    "overtime": "self", "help": "self", "box_reroll": "self",
    "box_free": "given", "level_up": "given", "task_energy": "given",
    "task_stardust": "given", "task_item": "given", "repair": "given", "fragment": "given",
    "carryover": "given", "cash_bonus": "given", "holiday_delay": "given",
    "explore": "judge", "daily_score": "judge", "fine": "judge",
    "adjust": "judge", "correction": "judge", "test": "judge",
    "expire_refund": "system",
}


def _act_amount(v):
    v = float(v or 0)
    if abs(v) < 1e-9:
        return ""
    return ("+" if v > 0 else "−") + ("%g" % abs(v))


def _act_items(ids):
    """这批流水牵扯到的券 / 卡（名字 + 数量），按流水 id 归堆。"""
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    out = {}
    for r in db.query(
            "SELECT li.ledger_id lid, li.qty_delta q, i.name, i.category, i.code, i.effect_json"
            " FROM ledger_item li JOIN item i ON i.id=li.item_id"
            " WHERE li.ledger_id IN (%s)" % q, list(ids)):
        out.setdefault(r["lid"], []).append(r)
    return out


def _item_label(x):
    """券要带上它能换多少 —— 「娱乐券」三个字看不出是 30 分钟还是 15 分钟。
    数字从 effect_json 里读，和用的时候读的是同一份，不会两处打架。"""
    name = x["name"]
    try:
        eff = json.loads(x["effect_json"] or "{}")
    except (TypeError, ValueError):
        eff = {}
    mins = float(eff.get("minutes") or 0)
    if mins:
        return "%s（%g 分钟）" % (name, mins)
    times = float(eff.get("times") or 0)
    if times > 1:
        return "%s（%g 次）" % (name, times)
    return name


def _act_item_text(its):
    """「娱乐券（30 分钟）×2」这种。数量是 1 就不写 ×1，省得满屏乘号。"""
    parts = []
    for name, qty in its.items():
        parts.append(name if abs(qty - 1) < 1e-9 else "%s×%g" % (name, qty))
    return "、".join(parts)


def _act_impact(r):
    """这一条对账的影响。谁少了谁的多了，一句话说清。

    读的是 ledger 的原始列名 —— 聚合查出来的行也是这几个名字
    （SUM 之后照样叫 delta_stardust），所以两种行都能直接喂进来。
    """
    parts = []
    for key, label in (("delta_stardust", "星尘"), ("delta_energy", "周能量"),
                       ("delta_minutes", "分钟"), ("delta_fragment", "碎片")):
        t = _act_amount(r[key])
        if t:
            parts.append(t + " " + label)
    debt = float(r["delta_debt"] or 0)
    if abs(debt) > 1e-9:
        parts.append(("记欠款 %g 星尘" % debt) if debt > 0
                     else ("免掉 %g 星尘欠款" % abs(debt)))
    return "　".join(parts)


def _act_text(kind, note, item_text, r):
    """一条流水的标题。优先用写流水时那句 note，它带着具体的东西，
    说不出来才退回「类型 + 金额」这种干巴巴的说法。"""
    n = note or ""
    if kind in ("task_stardust", "task_energy"):
        if kind == "task_energy" and n.startswith("周能量已满"):
            return n
        body = n.replace("任务奖励：", "")
        extra = "（翻倍卡 ×2）" if "翻倍" in body else ""
        title = body.split("（")[0].strip()
        # 老数据里那句 note 写的是「任务奖励：周能量 +2」，没有任务名，
        # 拆出来会变成「做完了『周能量 +2』」。看得出是机器写的，就别硬套。
        if title and "周能量" not in title and not title.startswith("+"):
            return "做完了「%s」%s" % (title, extra)
        return "做任务拿到星尘" if kind == "task_stardust" else "做任务拿到周能量"
    if kind == "task_item":
        return "任务奖励：%s" % (item_text or n.replace("任务奖励：", "").strip())
    if kind == "shop_ticket":
        return "买了券：%s" % (item_text or n.lstrip("购买 ").strip() or "一张券")
    if kind == "shop_card":
        return "买了卡：%s" % (item_text or n.lstrip("购买 ").strip() or "一张卡")
    if kind == "box_purchase":
        return n or "买了一个宝箱"
    if kind == "box_free":
        return ("开出：%s" % item_text) if item_text else (n or "发了一个宝箱")
    if kind == "box_reroll":
        return n or "把开出来的随机件重抽了一次"
    if kind == "level_up":
        return n or "升级奖励"
    if kind == "cash_exchange":
        return n or "换零花钱"
    if kind == "cash_bonus":
        return n or "零花钱翻倍生效"
    if kind == "ticket_use":
        return "用掉券：%s" % (item_text or n or "一张券")
    if kind == "card_use":
        return "用了卡：%s" % (item_text or n or "一张卡")
    if kind == "card_effect":
        return n or "卡片生效"
    if kind == "renew":
        return n or "续期"
    if kind == "fragment":
        return n or "碎片"
    if kind == "pool_deposit":
        return n or "往许愿池投了星尘"
    if kind == "overtime":
        return n or "加时"
    if kind == "help":
        return n or "按了求助"
    if kind == "holiday_delay":
        return n or "假期顺延"
    if kind == "expire_refund":
        return n or "到期折半返还"
    if kind == "explore":
        return "星星时刻：%s" % (n or "爸爸妈妈写了一句")
    if kind == "fine":
        return n or "校准扣减"
    if kind == "repair":
        return "修复任务做完，拿到：%s" % (item_text or n.replace("任务奖励：", "").strip() or "奖励")
    if kind == "daily_score":
        if "打分调整" in n:
            # 每天一条，note 开头那段日期在列表里是噪声
            return "打了分：%s" % (n.split("打分调整")[-1].strip() or "固定分")
        return n or "打分"
    if kind == "carryover":
        return n or "存量结转"
    if kind in ("adjust", "correction"):
        return n or ("手动调整" if kind == "adjust" else "修正")
    return (KINDS.get(kind, kind) + ("：" + n if n else ""))


def activity(member_id=None, *, days=None, group=None, limit=30, offset=0,
             since=None, until=None):
    """账本人话。member_id 传 None 是「全家」，不是「没指定」。

    同一次动作常常写两条流水（钱出去一条、东西进来一条），比如买券：
    一条 −10 星尘、一条 +1 张券。按「谁 + 什么时候 + 什么类型 + 那句话」
    拢成一条，家长看到的就是「花 10 星尘买了看动画 30 分钟」这一句，
    而不是两条各说一半的账。金额和东西在合并里各自求和，账还是对的。

    since / until 是「按日历翻」那一路（YYYY-MM-DD，两头都算在内，
    until 那天的 23:59:59 也算）；days 是「往回数几天」那一路。
    两路都给了就按日历那一路走 —— 家长在弹层里挑的是起止两天，
    换算成天数再筛会多带进来半天，不如直接用日期切。
    """
    ids = [int(member_id)] if member_id else [m["id"] for m in _kids()]
    if not ids:
        return {"items": [], "total": 0, "member_id": member_id}
    where = ["member_id IN (%s)" % ",".join("?" * len(ids)), "voided=0"]
    args = list(ids)
    if since or until:
        if since:
            where.append("ts>=?")
            args.append(str(since).strip() + " 00:00:00")
        if until:
            where.append("ts<=?")
            args.append(str(until).strip() + " 23:59:59")
    elif days:
        since = (_dtnow() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        where.append("ts>=?")
        args.append(since)
    if group:
        kinds = sorted(k for k, g in _KIND_GROUP.items() if g == group)
        if not kinds:
            return {"items": [], "total": 0, "member_id": member_id, "group": group}
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
        args += kinds
    w = " AND ".join(where)
    total = db.query_one(
        "SELECT COUNT(*) c FROM (SELECT 1 FROM ledger WHERE %s"
        " GROUP BY member_id, kind, ts, note)" % w, args)["c"]
    rows = db.query(
        "SELECT l.member_id, l.kind, l.ts, MAX(l.day) day, MIN(l.id) id,"
        " MAX(l.operator_id) op, l.note,"
        # v29：谁经手的。家长那边要的不是「爸爸妈妈」这个统称，
        # 是「这条是妈妈批的、那条是爸爸发的」——两个人各有一套口径时，
        # 没有名字就只能靠猜，猜错了就成了「你们大人说话不算数」。
        " MAX(om.name) by_name, MAX(om.role) by_role,"
        " SUM(l.delta_energy) delta_energy, SUM(l.delta_stardust) delta_stardust,"
        " SUM(l.delta_debt) delta_debt, SUM(l.delta_fragment) delta_fragment,"
        " SUM(l.delta_ticket) delta_ticket, SUM(l.delta_minutes) delta_minutes,"
        " GROUP_CONCAT(l.id) lids"
        " FROM ledger l LEFT JOIN member om ON om.id=l.operator_id"
        " WHERE %s GROUP BY l.member_id, l.kind, l.ts, l.note"
        " ORDER BY MIN(l.id) DESC LIMIT ? OFFSET ?" % w, args + [int(limit), int(offset)])
    all_ids = [int(x) for r in rows for x in str(r["lids"] or "").split(",") if x]
    imap = _act_items(all_ids)
    items = []
    for r in rows:
        its = {}
        for lid in str(r["lids"] or "").split(","):
            for x in imap.get(int(lid), []) if lid.strip() else []:
                label = _item_label(x)
                its[label] = its.get(label, 0.0) + float(x["q"] or 0)
        its = {k: v for k, v in its.items() if abs(v) > 1e-9}
        item_text = _act_item_text(its)
        g = _KIND_GROUP.get(r["kind"], "system")
        items.append({
            "id": r["id"], "ts": r["ts"], "day": r["day"], "kind": r["kind"],
            "kind_text": KINDS.get(r["kind"], r["kind"]),
            "group": g, "group_text": _GROUP_TEXT.get(g, "系统结算"),
            "member_id": r["member_id"], "who": member_name_of(r["member_id"]),
            "text": _act_text(r["kind"], r["note"], item_text, r),
            "impact": _act_impact(r),
            "items": [{"name": k, "qty": v} for k, v in its.items()],
            # 没记 operator_id 的是系统自己结的（惰性补结的周期结算那类）。
            # 写「系统」而不是孩子的名字：孩子没按过那个按钮。
            "by": r["by_name"] or "系统",
            "by_role": r["by_role"] or "",
            "by_parent": (r["by_role"] or "") in ("parent", "admin"),
            "note": r["note"] or "",
        })
    return {"items": items, "total": total, "member_id": member_id,
            "limit": int(limit), "offset": int(offset), "group": group, "days": days,
            "groups": [{"key": k, "text": t} for k, t in ACTIVITY_GROUPS]}


# ---------------------------------------------------------------------------
# 七个维度的报告（v28）：孩子端「分数」页用这一份
# ---------------------------------------------------------------------------
# 哪些流水算「被扣掉」：校准与罚款（fine）、作业复核撤销分项（daily_score）、
# 卡片带来的负分钟（card_effect）。买券买卡花掉的星尘不算 —— 那是他自己选的。
DEDUCT_KINDS = ("fine", "daily_score", "card_effect")


def dims_report(member_id, days=None):
    """七个维度逐项：这是什么、这个周期拿到几天、哪一项被扣过。

    孩子端的「分数」页看的是「这一项本身」，家长端的记录页看的是
    「哪一天缺了什么」（天 × 维度的矩阵）。两份是两种问法，不合并。

    窗口默认最近七天，不是「本周期」：周期可能今天才开，
    一进来七项全是 0/1 天，看不出孩子这一阵儿怎么样。
    周期本身的信息跟着返回，界面上另说一句。

    扣分和星星时刻都挂着 dimension_id，所以「哪一项被扣过」是查得出来的，
    不用让孩子对着一个总分猜。
    """
    cyc = current_cycle(member_id)
    end = parse_day(today())
    start = end - timedelta(days=max(1, int(days or 7)) - 1)
    span = (end - start).days + 1
    hist = score_history(member_id, days=span, until=fmt(end))
    d0, d1 = fmt(start), fmt(end)

    by_code = {}
    for x in hist["dims"]:
        meta = db.query_one("SELECT * FROM dimension WHERE code=?", (x["code"],))
        dim_id = meta["id"] if meta else None
        fines, stars = [], []
        if dim_id:
            for c in db.query("SELECT * FROM calibration WHERE member_id=? AND dimension_id=?"
                              " AND substr(ts,1,10) BETWEEN ? AND ? ORDER BY id DESC",
                              (member_id, dim_id, d0, d1)):
                fines.append({"ts": c["ts"], "reason": c["reason"] or "",
                              "effect": c["effect_type"] or "", "text": _calib_text(c)})
            for e in db.query("SELECT * FROM explore WHERE member_id=? AND dimension_id=?"
                              " AND day BETWEEN ? AND ? ORDER BY id DESC", (member_id, dim_id, d0, d1)):
                stars.append({"day": e["day"], "phrase": e["phrase"] or "",
                              "energy": float(e["energy"] or 0), "stardust": float(e["stardust"] or 0)})
        days_list = []
        for it in hist["days"]:
            cell = None
            for c in it["cells"]:
                if c["code"] == x["code"]:
                    cell = c
                    break
            days_list.append({"day": it["day"], "scored": it["scored"],
                              "got": bool(cell and cell["got"]),
                              "note": (cell or {}).get("note") or ""})
        by_code[x["code"]] = {
            "code": x["code"], "name": x["name"], "icon": x["icon"],
            "meaning": (meta["meaning"] if meta else "") or "",
            "score": float(meta["score"]) if meta else 1.0,
            "hit": x["hit"], "total": x["total"], "rate": x["rate"],
            "days": days_list, "fines": fines, "stars": stars,
        }

    # 这一段里固定分之外的加减。改分和作业复核也走 daily_score 这个类型，
    # 所以不能按类型把 daily_score 整类过滤掉 —— 那正是「哪里被扣了」的答案。
    #
    # 时间窗按 day 判，但 day 是空的就回落到 ts：罚款那几条就没写 day
    # （它不挂在某一天上），只按 day 过滤的话，孩子被罚了 10 星尘，
    # 这一页一句都不提 —— 那是最该说出来的一笔。
    deduct = {"times": 0, "minutes": 0.0, "stardust": 0.0}
    extra = []
    for r in db.query(
            "SELECT * FROM ledger WHERE member_id=? AND voided=0"
            " AND (CASE WHEN day IS NULL OR day='' THEN substr(ts,1,10) ELSE day END)"
            "     BETWEEN ? AND ? ORDER BY id DESC", (member_id, d0, d1)):
        if not any(float(r[k] or 0) for k in
                   ("delta_energy", "delta_stardust", "delta_debt", "delta_minutes")):
            continue
        if r["kind"] == "card_effect":
            extra.append({"kind": r["kind"], "text": _act_text(r["kind"], r["note"], "", r),
                          "impact": _act_impact(r), "ts": r["ts"], "neg": False})
            continue
        # 「被扣掉」和「自己花掉」是两件事：买券花的 14 星尘是他自己选的，
        # 算进「被扣了多少」会让他觉得花自己的钱也是挨罚。
        # 只有家长或系统给的后果才算扣减。
        neg = (r["kind"] in DEDUCT_KINDS
               and (float(r["delta_stardust"] or 0) < 0 or float(r["delta_debt"] or 0) > 0
                    or float(r["delta_minutes"] or 0) < 0 or float(r["delta_energy"] or 0) < 0))
        if neg:
            deduct["times"] += 1
            deduct["minutes"] = round(deduct["minutes"] + abs(min(0.0, float(r["delta_minutes"] or 0))), 2)
            deduct["stardust"] = round(deduct["stardust"] + abs(min(0.0, float(r["delta_stardust"] or 0))), 2)
        extra.append({"kind": r["kind"], "text": _act_text(r["kind"], r["note"], "", r),
                      "impact": _act_impact(r), "ts": r["ts"], "neg": neg})

    order = [x["code"] for x in dimensions("school")]
    dims = [by_code[c] for c in order if c in by_code]
    ranked = [d for d in dims if d["total"]]
    weakest = min(ranked, key=lambda d: (d["hit"], d["rate"])) if ranked else None
    judged = [d for d in dims if d["hit"] < d["total"]]
    return {
        "member_id": member_id, "start": d0, "end": d1,
        "cycle": {"start_date": cyc["start_date"], "end_date": cyc["end_date"]} if cyc else None,
        "dims": dims, "extra": extra[:40], "deduct": deduct,
        "total": hist["total"],
        "weakest": ({"code": weakest["code"], "name": weakest["name"],
                     "hit": weakest["hit"], "total": weakest["total"]} if weakest else None),
        "imperfect": [{"code": d["code"], "name": d["name"],
                       "miss": d["total"] - d["hit"]} for d in judged],
    }


def _calib_text(c):
    """校准那一句话：扣了什么都写明白，别只留一个「校准」两个字。"""
    eff = json.loads(c["effect_json"] or "{}") if c["effect_json"] else {}
    bits = []
    if float(eff.get("minutes") or 0):
        bits.append("扣 %g 分钟" % abs(float(eff["minutes"])))
    if float(eff.get("stardust") or 0):
        bits.append("扣 %g 星尘" % abs(float(eff["stardust"])))
    if float(eff.get("debt") or 0):
        bits.append("记欠款 %g 星尘" % float(eff["debt"]))
    if eff.get("task_id") or c["effect_type"] == "task":
        bits.append("要做一件修复任务")
    if c["effect_type"] == "device":
        bits.append("设备改到公共区域用 3 天")
    tail = ("（" + "，".join(bits) + "）") if bits else ""
    return (c["reason"] or "校准") + tail


# ---------------------------------------------------------------------------
# 星球等级（v13 补回 v2 设计稿）
# ---------------------------------------------------------------------------
def level_table():
    """等级表：门槛公式 25 × n × (n−1)，称号与升级奖励都在设置里，可改。"""
    row = db.query_one("SELECT value FROM setting WHERE key='level.tiers'")
    if not row:
        return []
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return []


# 给余额、但不进「累计获得」的流水类型。
#
# 等级看的是累计获得（lifetime_stardust），而每次升级会补发券和卡。
# 纸质账搬进来的存量是这个孩子在系统外面攒的，让他一进来就跳几级、
# 连带补出一批升级奖励，等于白送；所以这一条要排除掉。
LEVEL_EXCLUDED_KINDS = ("carryover",)


def lifetime_stardust(member_id):
    """累计获得，不是余额。花出去的不扣，所以等级只增不减。

    「存量结转」不算在里面，见 LEVEL_EXCLUDED_KINDS。余额照常用，
    只是等级要从这个系统里真正挣到的星尘开始算。
    """
    sql = ("SELECT COALESCE(SUM(delta_stardust),0) v FROM ledger"
           " WHERE member_id=? AND delta_stardust>0 AND voided=0")
    args = [member_id]
    if LEVEL_EXCLUDED_KINDS:
        sql += " AND kind NOT IN (%s)" % ",".join("?" * len(LEVEL_EXCLUDED_KINDS))
        args.extend(LEVEL_EXCLUDED_KINDS)
    return round(db.query_one(sql, tuple(args))["v"], 2)


def level_of(member_id):
    tiers = level_table()
    if not tiers:
        return None
    total = lifetime_stardust(member_id)
    cur = tiers[0]
    nxt = None
    for t in tiers:
        if total + 1e-9 >= t["threshold"]:
            cur = t
        elif nxt is None:
            nxt = t
    span = (nxt["threshold"] - cur["threshold"]) if nxt else 0
    done = (total - cur["threshold"]) if nxt else span
    pct = int(round(done / span * 100)) if span else 100
    return {
        "total": total,
        "level": cur["level"],
        "title": cur["title"],
        "threshold": cur["threshold"],
        "next": ({"level": nxt["level"], "title": nxt["title"],
                  "threshold": nxt["threshold"]} if nxt else None),
        "need": round(nxt["threshold"] - total, 2) if nxt else 0,
        "percent": max(0, min(100, pct)),
    }


def apply_level_rewards(member_id, operator_id=None):
    """等级涨了就补发升级奖励。幂等：已发过的等级记在流水里，不重复发。"""
    if not is_player(member_id):
        return []
    lv = level_of(member_id)
    if not lv:
        return []
    granted = []
    for t in level_table():
        if t["level"] > lv["level"] or t["level"] == 1:
            continue
        done = db.query_one(
            "SELECT 1 FROM ledger WHERE member_id=? AND kind='level_up' AND ref_id=? AND voided=0",
            (member_id, t["level"]))
        if done:
            continue
        for g in t.get("rewards", []):
            code = g.get("code")
            if code:
                it = item_by_code(code)
                if not it:
                    continue
                grant_item(member_id, it["id"], g.get("qty", 1), source="levelup",
                           note="升到 Lv.%d %s" % (t["level"], t["title"]),
                           operator_id=operator_id)
                continue
            # 按稀有度随机抽一张（优先图鉴里还没有的）
            rar = g.get("card_rarity")
            if rar:
                card = pick_card(member_id, rar)
                if card:
                    grant_item(member_id, card["id"], g.get("qty", 1), source="levelup",
                               note="升到 Lv.%d %s" % (t["level"], t["title"]),
                               operator_id=operator_id)
        add_ledger(member_id, "level_up", ref_type="level", ref_id=t["level"],
                   note="升到 Lv.%d %s" % (t["level"], t["title"]), operator_id=operator_id,
                   meta={"level": t["level"], "title": t["title"]})
        push_notify(member_id, "level", "星球升级",
                    "升到 Lv.%d %s" % (t["level"], t["title"]))
        granted.append({"level": t["level"], "title": t["title"]})
    return granted


def to_ticket_list(member_id):
    out = []
    for it in db.query("SELECT * FROM item WHERE category='ticket' AND active=1 ORDER BY sort"):
        q = item_balance(member_id, it["id"])
        if q > 0:
            out.append({"id": it["id"], "code": it["code"], "name": it["name"], "qty": q,
                        # 按今天算面值：周末翻倍开着的时候，周六打开就是 60。
                        # 显示「现在用值多少」比显示「建库时是多少」有用。
                        "price": it["price"], "minutes": ticket_minutes(it, today()),
                        "desc": it["desc"], "limit": it["weekly_limit"], "icon": it["icon"]})
    return out


def to_card_list(member_id):
    out = []
    for h in db.query(
            "SELECT h.*, i.name, i.rarity, i.card_no, i.desc, i.effect_key, i.icon, i.max_hold"
            " FROM holding h JOIN item i ON i.id=h.item_id"
            " WHERE h.member_id=? AND h.qty>0 AND i.category='card'"
            " ORDER BY CASE i.rarity WHEN 'diamond' THEN 0 WHEN 'legend' THEN 1 WHEN 'rare' THEN 2 ELSE 3 END,"
            " i.sort", (member_id,)):
        left = None
        if h["expires_at"]:
            left = (parse_day(h["expires_at"]) - parse_day(today())).days
        out.append({"holding_id": h["id"], "name": h["name"], "rarity": h["rarity"],
                    "card_no": h["card_no"], "desc": h["desc"], "qty": h["qty"],
                    "effect": h["effect_key"], "source": h["source"],
                    "expires_at": h["expires_at"], "days_left": left, "icon": h["icon"],
                    "renew_count": h["renew_count"]})
    return out


# ---------------------------------------------------------------------------
# 周期结算
# ---------------------------------------------------------------------------
def has_double_week(member_id, cycle_start):
    for r in db.query(
            "SELECT iu.meta FROM item_use iu JOIN item i ON i.id=iu.item_id"
            " WHERE iu.member_id=? AND i.code='double_week'", (member_id,)):
        try:
            if json.loads(r["meta"] or "{}").get("cycle_start") == cycle_start:
                return True
        except (TypeError, ValueError):
            pass
    return False


def settle_cycle(cycle_id, operator_id=None):
    """周期结算：星尘按本周固定分一次性入账，再按周能量发免费宝箱。"""
    c = recalc_cycle(cycle_id)
    if not c:
        return {"ok": False, "msg": "周期不存在"}
    if not is_player(c["member_id"]):
        return {"ok": False, "msg": PARENT_MSG}
    if c["status"] == "settled":
        return {"ok": False, "msg": "本周期已结算"}

    m = db.query_one("SELECT * FROM member WHERE id=?", (c["member_id"],))
    rate = float(db.cfg("rate.fixed_to_stardust", 1))
    demo_only = (m["role"] == "parent" and (m["parent_yield_policy"] or "none") == "none")

    gross = 0.0 if demo_only else round((c["fixed_score"] or 0) * rate, 2)
    doubled = False
    if gross > 0 and has_double_week(c["member_id"], c["start_date"]):
        gross = round(gross * 2, 2)
        doubled = True

    offset = min(max(0.0, debt_balance(c["member_id"])), gross)
    net = round(gross - offset, 2)
    if offset > 0:
        add_ledger(c["member_id"], "fine", cycle_id=cycle_id, debt=-offset, operator_id=operator_id,
                   note="周期结算：星尘欠款优先抵扣")
    # 滚过一个周期还没还完的，免掉。无限往下滚会变成长期负债，
    # 孩子算一下就知道「反正欠着也一样」，这条线就废了（第 08 章）。
    left_debt = round(max(0.0, debt_balance(c["member_id"])), 2)
    forgiven = 0.0
    if left_debt > 0:
        forgiven = left_debt
        add_ledger(c["member_id"], "fine", cycle_id=cycle_id, debt=-forgiven,
                   operator_id=operator_id,
                   note="周期结算：欠款已滚过一个周期，免掉 %g 星尘" % forgiven)

    # 券的负库存走同一个结算口、同一套条件（第 05、08 章，唯一口径）：
    # 本周固定分达标就清零；没达标则最多保留 30 分钟滚到下个周期，再往下不累加。
    threshold = float(db.cfg("cycle.debt_clear_score", 28)) * (c["threshold_ratio"] or 1.0)
    cleared_minutes = kept_minutes = 0.0
    debt_min = minutes_debt(c["member_id"])
    if debt_min > 0:
        keep_cap = float(db.cfg("cycle.debt_keep_minutes", 30))
        if float(c["fixed_score"] or 0) + 1e-9 >= threshold:
            keep = 0.0
        else:
            keep = min(debt_min, keep_cap)
        cut = round(debt_min - keep, 2)
        if cut > 0:
            add_ledger(c["member_id"], "fine", cycle_id=cycle_id, minutes=cut, operator_id=operator_id,
                       note="周期结算：本周达标，欠的 %g 分钟清零" % cut if keep == 0
                       else "周期结算：欠的 %g 分钟里免掉 %g，只保留 %g 滚到下个周期"
                            % (debt_min, cut, keep))
            cleared_minutes = cut
        kept_minutes = keep
    if net > 0:
        add_ledger(c["member_id"], "daily_score", cycle_id=cycle_id, stardust=net,
                   operator_id=operator_id,
                   note="周期结算：固定分 %g 分入账%s" % (c["fixed_score"] or 0,
                                                "（双倍周）" if doubled else ""),
                   meta={"double_week": doubled, "offset": offset})

    # v38 的③：上个周期发下去、一直没点的箱子，这次结算顺手替他开掉。
    # 摆在发本周期这只箱子之前 —— auto_open_stale 按 ts 过滤（ts 早于正在
    # 结算这个周期的 start_date 才算陈箱），本周期刚发的那只不会被误伤。
    # 任务奖励发的箱子没绑周期，所以判据只能是时间。
    auto_opened = auto_open_stale(c["member_id"], before_day=c["start_date"],
                                  operator_id=operator_id)

    tier = None if demo_only else tier_for_energy(c["energy"], c["threshold_ratio"],
                                                 c["fixed_score"])
    box = issue_box(c["member_id"], tier["tier"], cycle_id=cycle_id, source="free",
                    operator_id=operator_id) if tier else None

    db.execute("UPDATE cycle SET status='settled', settled_at=?, tier_awarded=?, stardust_grant=?"
               " WHERE id=?",
               (now(), tier["tier"] if tier else 0, net, cycle_id))
    push_notify(c["member_id"], "settle", "本周结算完成",
                "本周 %g 分，星尘 +%g%s" % (c["energy"], net,
                                          ("，" + tier["name"] + "已到你的宝箱页，点开看看")
                                          if box else ""))
    levels = apply_level_rewards(c["member_id"], operator_id=operator_id)
    # 周期一换，「连续达标 N 周」「本周期固定分」这两类心愿的进度就重算了，
    # 刚够的话在这里报出来。
    check_wish_ready(c["member_id"])
    return {"ok": True, "cycle": cycle_snapshot(cycle_id), "stardust": net, "offset": offset,
            "forgiven": forgiven, "cleared_minutes": cleared_minutes, "kept_minutes": kept_minutes,
            "doubled": doubled, "box": box, "auto_opened": auto_opened, "level_up": levels}


def ensure_settled(member_id, day=None):
    """把已经过期但还没结算的周期补结掉（惰性触发，不需要定时任务）。"""
    d = day or today()
    rows = db.query("SELECT id FROM cycle WHERE member_id=? AND status='open' AND end_date<?"
                    " ORDER BY start_date", (member_id, d))
    return [settle_cycle(r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# 宝箱
# ---------------------------------------------------------------------------
def _random_value(rnd):
    """给随机件估个值，用来比「两次抽奖哪个更好」。

    只比档位，不比具体东西：随机件池里三种东西的定价本来就是按稀有度排的。
    """
    order = {"legend": 400, "rare": 120, "common": 40, "diamond": 600}
    if rnd.get("resolved_item"):
        it = db.query_one("SELECT rarity FROM item WHERE id=?", (rnd["resolved_item"],))
        # query_one 给的是 sqlite3.Row，没有 .get。以前这里写 it.get(...)，
        # 只要开出的是卡类随机件、而且手上有装填好的重抽券，开箱就直接 500。
        # 自动重抽那条路平时很少走到，一直没暴露。
        base = order.get(it["rarity"] if it else "", 50)
    elif rnd.get("code") == "@common_pick":
        # 自选件到这一刻还没定是哪张，按普通卡的档位估（qty 张）。
        # 不给它估值的话自选件的价值是 0，装了重抽券时会被无条件换掉。
        base = order.get("common", 40) * max(1, int(rnd.get("qty", 1) or 1))
    elif rnd.get("kind") == "bonus":
        base = float(rnd.get("qty", 0) or 0) * 1.2
    elif rnd.get("kind") == "privilege":
        base = float(rnd.get("price", 0) or 0)
    else:
        base = 0
    return base * float(rnd.get("qty", 1) or 1)


def _grant_random(member_id, rnd, tier_name, box_id, *, cycle_id=None, operator_id=None,
                  source="box"):
    """把随机件真正发到手上。开箱和重抽共用这一段 —— 两处各写一遍的话，
    「重抽拿到的东西比开箱那次少一样」这种事迟早会发生。

    「一次加时 60 分钟」记成当天的额度（正数），核销时算进今天还能用多少。
    """
    kind = "box_free" if source == "box" else "box_reroll"
    ri = rnd.get("resolved_item")
    rkind = rnd.get("kind")
    if ri and rkind in ("ticket", "card"):
        grant_item(member_id, ri, rnd.get("qty", 1), source="box", kind=kind,
                   ref_type="box_open", ref_id=box_id, cycle_id=cycle_id,
                   operator_id=operator_id,
                   note="%s 随机件：%s" % (tier_name, rnd.get("label") or rnd.get("name")))
    elif rkind == "bonus" and rnd.get("code") == "minutes":
        qty = float(rnd.get("qty", 0) or 0)
        if qty:
            add_ledger(member_id, kind, cycle_id=cycle_id, day=today(), minutes=qty,
                       ref_type="box_open", ref_id=box_id, operator_id=operator_id,
                       note="%s 随机件：今天多 %g 分钟" % (tier_name, qty))
    elif rkind == "privilege":
        priv = item_by_code(rnd.get("code", ""))
        if priv:
            grant_item(member_id, priv["id"], 1, source="box", kind=kind,
                       ref_type="box_open", ref_id=box_id, cycle_id=cycle_id,
                       operator_id=operator_id,
                       note="%s 随机件：%s" % (tier_name, priv["name"]))
    return {"type": "random", "name": rnd.get("name") or rnd.get("label"),
            "label": rnd.get("label"), "detail": rnd,
            "pick_required": rnd.get("pick_required", False)}


def _take_back_random(member_id, rnd, box_id, operator_id=None):
    """把上一件随机件收回来。重抽必须先退再发，不然就是白拿两件。"""
    ri = rnd.get("resolved_item")
    rkind = rnd.get("kind")
    qty = float(rnd.get("qty", 1) or 1)
    note = "重抽退回：" + (rnd.get("label") or rnd.get("name") or "随机件")
    if ri and rkind in ("ticket", "card"):
        consume_item(member_id, ri, qty, kind="box_reroll", note=note, operator_id=operator_id)
    elif rkind == "bonus" and rnd.get("code") == "minutes":
        if qty:
            add_ledger(member_id, "box_reroll", day=today(), minutes=-qty,
                       ref_type="box_open", ref_id=box_id, operator_id=operator_id, note=note)
    elif rkind == "privilege":
        priv = item_by_code(rnd.get("code", ""))
        if priv:
            consume_item(member_id, priv["id"], 1, kind="box_reroll", note=note,
                         operator_id=operator_id)


def reroll_box_random(member_id, box_id, operator_id=None):
    """开完箱看着结果，再决定要不要为这一箱花一张重抽卡。

    和「装填」那条路的区别：装填是开箱前就把卡押上，系统自动抽两次取好的；
    这条是开箱之后孩子看着结果决定。两者都取价值更高的那个 ——
    重抽不是赌。开出更差的那一下会让孩子觉得自己被坑了，而这个系统不靠
    「让你后悔」来制造张力。花掉的是一张卡，不是一次运气。

    卡一定消耗：不管第二次抽得更好还是一样，卡花出去了不退回。
    能抽两次还能退卡，等于这一箱保底两个随机件。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    b = db.query_one("SELECT * FROM box_open WHERE id=?", (box_id,))
    if not b or b["member_id"] != member_id:
        return {"ok": False, "msg": "没有这一箱"}
    rnd = json.loads(b["random_json"] or "{}")
    if not rnd:
        return {"ok": False, "msg": "这一箱没有随机件，没什么可重抽的"}
    if rnd.get("rerolled"):
        return {"ok": False, "msg": "这一箱已经重抽过了，一箱只能重抽一次"}
    # 自选件在「还没挑」的时候可以换掉 —— 决定权还在他手上，换个结果不算反悔。
    # 挑完了就是他自己定下来的，那一下不给重抽（这才是「你自己选的」）。
    if rnd.get("picked"):
        return {"ok": False, "msg": "这几张是你自己挑的，不用重抽"}

    card = item_by_code("reroll_card")
    if not card or item_balance(member_id, card["id"]) < 1:
        return {"ok": False, "msg": "手上没有重抽券了"}
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (b["tier"],))

    got = consume_item(member_id, card["id"], 1, kind="card_use",
                       note="重抽第 %d 箱的随机件" % box_id, operator_id=operator_id)
    if got != 0:
        return {"ok": False, "msg": "这张重抽券扣不掉，稍后再试"}

    again = pick_random_from_pool(member_id, t)
    # 池子只有三件，抽到一模一样就等于白花一张卡。给两次机会换个不一样的，
    # 还是一样就认了 —— 再抽下去就不是「不满意再要一次」，是刷。
    for _ in range(2):
        if not again or _random_value(again) != _random_value(rnd) or \
                again.get("label") != rnd.get("label"):
            break
        again = pick_random_from_pool(member_id, t)

    if not again or _random_value(again) <= _random_value(rnd):
        # 没换成也要把这一箱标成「重抽过了」。不标的话孩子可以对着同一箱
        # 一直花卡 —— 每次都是独立事件，总有一次会抽到更好的，
        # 那这张卡就成了「保底换到最好」，不是「再给你一次机会」。
        rnd["rerolled"] = True
        db.execute("UPDATE box_open SET random_json=? WHERE id=?",
                   (json.dumps(rnd, ensure_ascii=False), box_id))
        return {"ok": True, "changed": False, "box_id": box_id,
                "note": "再抽了一次，还是原来那件更好，就留着原来这件。重抽券已经用掉了。"}

    _take_back_random(member_id, rnd, box_id, operator_id=operator_id)
    again["rerolled"] = True
    # 换出来的这一件也可能正是自选件（池子里本来就有）。自选件不预先定是哪张，
    # 走 _grant_random 会一件都发不出去 —— 那一箱就白换了。两条路并成一条。
    need_pick, given = _grant_random_or_pick(member_id, again, t, box_id,
                                             cycle_id=b["cycle_id"],
                                             operator_id=operator_id,
                                             source="reroll")
    db.execute("UPDATE box_open SET random_json=? WHERE id=?",
               (json.dumps(again, ensure_ascii=False), box_id))
    return {"ok": True, "changed": True, "box_id": box_id,
            "given": given, "need_pick": need_pick, "random": again,
            "note": ("换成了更好的一件。重抽券已经用掉了。"
                     + ("这几张还得你自己挑。" if need_pick else ""))}


def box_cards(t):
    """这一档的保底高级件，有序列表，永远返回 [{"rarity","count"}, ...]。

    v24 起保底卡可以不止一张（完美箱是普 + 稀 + 传各一张），所以从 cards_json 读。
    老库在 _migrate_v24 跑过之后也一定有这个列；万一读到空，
    退回旧的 card_rarity / card_count 两列，免得历史库里那些箱子凭空少一张卡。
    """
    raw = t["cards_json"] if "cards_json" in t.keys() else ""
    if raw:
        try:
            items = json.loads(raw)
        except Exception:
            items = []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            rar = it.get("rarity") or ""
            try:
                n = int(it.get("count", 1) or 0)
            except Exception:
                n = 0
            if rar and n > 0:
                out.append({"rarity": rar, "count": n})
        if out:
            return out
    if t["card_rarity"]:
        return [{"rarity": t["card_rarity"], "count": max(1, int(t["card_count"] or 1))}]
    return []


def issue_box(member_id, tier, *, cycle_id=None, source="free", operator_id=None, cost=0):
    """发一只箱子（待开）。箱子里有什么，压到 open_box 那一刻才抽。

    v38 之前这一段是「发箱即发货」：券、保底卡、随机件在同一次调用里全发完，
    所以孩子手上从来没有过一只待开的箱子，随机件那 10/20/40/70% 也只是后台
    一次静默抽奖。拆开之后三条发箱的路各有各的后续：

      · 周期结算、任务奖励 → 只落一条 opened_at IS NULL 的记录，等孩子来开
      · 直购 → buy_box 落完记录立刻 open_box（付完星尘当场开）

    兑换、发件全在 open_box 里，这里什么都不发。
    """
    if not is_player(member_id):
        return None
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (tier,))
    if not t:
        return {"ok": False, "msg": "没有这一档宝箱"}
    if source == "purchase" and not t["purchase_allowed"]:
        return {"ok": False, "msg": "%s 不零售" % t["name"]}

    box_id = db.execute(
        "INSERT INTO box_open (member_id, cycle_id, tier, source, tickets, stardust,"
        " card_item_id, diamond_item_id, random_json, cost, ts, operator_id, opened_at)"
        " VALUES (?,?,?,?,0,0,NULL,NULL,'{}',?,?,?,NULL)",
        (member_id, cycle_id, tier, source, cost, now(), operator_id))
    return {"ok": True, "box_id": box_id, "tier": tier, "name": t["name"],
            "source": source, "pending": True, "cost": cost,
            "icon": t["icon"] or ""}


def open_box(member_id, box_id, *, picks=None, operator_id=None, auto=False):
    """打开一只箱子：抽内容、发货。

    券和保底卡当场到账。随机件里只有 @common_pick 是自选件，它不预先定好是哪张：
    picks 给了就按 picks 发，auto 或者没给（超时兜底 / 直购）就由系统按
    「优先给图鉴里还没有的」代选。这时返回里 need_pick 非空 —— 箱子已经算开过
    （opened_at 有值），但自选那几张还没到手上，等 resolve_box_pick 收尾。

    一只箱子只能开一次，重入直接拒。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    b = db.query_one("SELECT * FROM box_open WHERE id=?", (box_id,))
    if not b or b["member_id"] != member_id:
        return {"ok": False, "msg": "没有这一箱"}
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (b["tier"],))
    if not t:
        return {"ok": False, "msg": "没有这一档宝箱"}
    if b["opened_at"]:
        # 开过了、但自选那几张还悬着：这不是「想再开一次」，是回来把没挑完的
        # 挑完。重新点一次提醒卡就该回到那一屏，而不是甩一句「已经开过了」——
        # 甩了等于把自选锁死，孩子只能等下个周期结算让系统替他挑。
        rnd0 = json.loads(b["random_json"] or "{}")
        need = _pending_pick_need(rnd0) if (rnd0.get("pick_required")
                                            and not rnd0.get("picked")) else None
        if need:
            return {"ok": True, "box_id": box_id, "tier": b["tier"], "name": t["name"],
                    "source": b["source"], "given": [], "random": rnd0, "cost": b["cost"],
                    "need_pick": need, "resume": True, "icon": t["icon"] or ""}
        return {"ok": False, "msg": "这一箱已经开过了"}

    cycle_id = b["cycle_id"]
    free = (b["source"] == "free")
    # 保底高级件可以有好几张（完美箱三张）。每张按稀有度各抽一次，
    # 同一箱里抽到同一张卡也照发 —— 抽取顺序取「从普通到传说」，
    # 稀有度高的后抽，这样优先给未拥有的那条逻辑不会被低稀有度提前占掉。
    cards = []
    for c in sorted(box_cards(t), key=lambda x: RARITY_ORDER.get(x["rarity"], 9)):
        for _i in range(c["count"]):
            one = pick_card(member_id, c["rarity"])
            if one:
                cards.append(one)
    rnd = None
    if free and t["random_rate"] > 0 and random.random() < t["random_rate"]:
        rnd = pick_random_from_pool(member_id, t)
        # 装填的重抽券：开出结果之后如果手上还压着一张，就再抽一次，取价值更高的
        # 那个。自选件在这里也可以被换掉（重抽挪到「挑之前」），换掉了就不必再挑。
        if rnd and consume_armed(member_id, "reroll_random"):
            again = pick_random_from_pool(member_id, t)
            if again and _random_value(again) > _random_value(rnd):
                rnd = again
                rnd["rerolled"] = True
    dia = None
    if free and t["diamond_rate"] > 0 and random.random() < t["diamond_rate"]:
        dia = pick_card(member_id, "diamond")

    kind = "box_free" if free else "box_purchase"
    given = []

    fun = item_by_code("ticket_fun")
    if t["tickets"] and fun:
        grant_item(member_id, fun["id"], t["tickets"], source="box", kind=kind,
                   ref_type="box_open", ref_id=box_id, cycle_id=cycle_id,
                   operator_id=operator_id,
                   note="%s 保底：娱乐券 ×%g" % (t["name"], t["tickets"]))
        given.append({"type": "ticket", "name": "娱乐券", "qty": t["tickets"]})

    if t["stardust"]:
        add_ledger(member_id, kind, cycle_id=cycle_id, stardust=t["stardust"],
                   ref_type="box_open", ref_id=box_id, operator_id=operator_id,
                   note="%s 保底：星尘 +%g" % (t["name"], t["stardust"]))
        given.append({"type": "stardust", "name": "星尘", "qty": t["stardust"]})

    for card in cards:
        frag = grant_item(member_id, card["id"], 1, source="box", kind=kind,
                          ref_type="box_open", ref_id=box_id, cycle_id=cycle_id,
                          operator_id=operator_id,
                          note="%s 高级件：%s" % (t["name"], card["name"]))[2]
        given.append({"type": "card", "name": card["name"], "rarity": card["rarity"],
                      "fragment": frag})

    need_pick, rnd_given = _grant_random_or_pick(
        member_id, rnd, t, box_id, picks=picks, auto=auto,
        cycle_id=cycle_id, operator_id=operator_id)
    given += rnd_given

    if dia:
        grant_item(member_id, dia["id"], 1, source="box", kind=kind, ref_type="box_open",
                   ref_id=box_id, cycle_id=cycle_id, operator_id=operator_id,
                   note="完美箱 钻石级：%s" % dia["name"])
        given.append({"type": "diamond", "name": dia["name"]})

    db.execute("UPDATE box_open SET tickets=?, stardust=?, card_item_id=?, diamond_item_id=?,"
               " random_json=?, opened_at=? WHERE id=?",
               (t["tickets"], t["stardust"], cards[0]["id"] if cards else None,
                dia["id"] if dia else None, json.dumps(rnd or {}, ensure_ascii=False),
                now(), box_id))

    return {"ok": True, "box_id": box_id, "tier": b["tier"], "name": t["name"],
            "source": b["source"], "given": given, "random": rnd, "cost": b["cost"],
            "need_pick": need_pick, "icon": t["icon"] or "",
            "note": ("这一档没有随机件，开出什么在买之前就写清楚了" if not free else "")}


def _pending_pick_need(rnd):
    """自选件还没挑完时，给前端的那一份「还差几张、候选人是谁」。

    开箱那一屏和「回来接着挑」那一屏共用它，两处各拼一遍的话，
    补上来的那份迟早跟候选人表对不上。
    """
    opts = (rnd or {}).get("pick_options") or []
    if not opts:
        return None
    return {"qty": max(1, int((rnd or {}).get("qty", 1) or 1)), "rarity": "common",
            "name": "自选普通卡", "options": opts}


def _grant_random_or_pick(member_id, rnd, t, box_id, *, picks=None, auto=False,
                          cycle_id=None, operator_id=None, source="box"):
    """随机件的发法：普通件直接发；自选件要么按 picks 发，要么挂起等孩子挑。

    返回 (need_pick, given)，两件事不会同时发生：
      · need_pick 非空 → 东西还没到手上，候选已经算好写进 rnd["pick_options"]，
        等 resolve_box_pick 收尾
      · given 非空 → 已经发出去了

    source 一路透到发卡那一步，只影响流水归类（开箱发的 / 重抽换的）。
    """
    if not rnd:
        return None, []
    if not rnd.get("pick_required"):
        return None, [_grant_random(member_id, rnd, t["name"], box_id,
                                    cycle_id=cycle_id, operator_id=operator_id,
                                    source=source)]

    opts = pick_candidates(member_id, "common")
    want = max(1, int(rnd.get("qty", 1) or 1))
    requested = [str(x) for x in (picks or []) if x]
    # 候选不够挑（卡池被持有上限卡住）：把能给的直接给掉，别让孩子对着一屏
    # 凑不满的候选点不出来。这时「两张不同」自然退化成「有几张给几张」。
    if len(opts) <= want:
        requested = [c["code"] for c in opts]
    elif not requested and auto:
        requested = [c["code"] for c in opts[:want]]

    if requested:
        given = _grant_pick_cards(member_id, rnd, requested, opts, t, box_id,
                                  cycle_id=cycle_id, operator_id=operator_id,
                                  source=source)
        if given:
            return None, given
        rnd.pop("picked", None)     # 有对不上的 code：退回让孩子重挑，不静默换别的

    rnd["pick_options"] = [_card_brief(c) for c in opts]
    return _pending_pick_need(rnd), []


def _grant_pick_cards(member_id, rnd, codes, opts, t, box_id, *, cycle_id=None,
                      operator_id=None, source="box"):
    """把自选出来的那几张（必须互不相同）发到手上。挑不满或者挑重了返回空。

    kind 跟 _grant_random 一个口径：重抽换出来的记 box_reroll，开箱当天发的
    记 box_free。两处各写一套的话，「重抽拿到的东西流水归错类」迟早会发生。
    """
    by_code = {c["code"]: c for c in opts}
    want = max(1, int(rnd.get("qty", 1) or 1))
    picked, seen = [], set()
    for code in codes:
        c = by_code.get(code)
        if not c or code in seen:
            return []
        seen.add(code)
        picked.append(c)
    if len(picked) != want:
        return []
    given = []
    for c in picked:
        frag = grant_item(member_id, c["id"], 1, source="box",
                          kind=("box_reroll" if source == "reroll" else "box_free"),
                          ref_type="box_open", ref_id=box_id, cycle_id=cycle_id,
                          operator_id=operator_id,
                          note="%s 随机件：自选 %s" % (t["name"], c["name"]))[2]
        given.append({"type": "card", "name": c["name"], "rarity": c["rarity"],
                      "picked": True, "fragment": frag})
    rnd["picked"] = [c["code"] for c in picked]
    return given


def resolve_box_pick(member_id, box_id, codes, *, operator_id=None, auto=False):
    """孩子看完候选，把自选件那几张挑出来交上去。

    一箱只挑一次。挑不满、挑重了、挑了候选之外的，一律退回让他重挑，
    不静默换成别的 —— 这一屏存在的意义就是「他说了算」。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    b = db.query_one("SELECT * FROM box_open WHERE id=?", (box_id,))
    if not b or b["member_id"] != member_id:
        return {"ok": False, "msg": "没有这一箱"}
    if not b["opened_at"]:
        return {"ok": False, "msg": "这一箱还没开"}
    rnd = json.loads(b["random_json"] or "{}")
    if not rnd.get("pick_required"):
        return {"ok": False, "msg": "这一箱没有要挑的东西"}
    if rnd.get("picked"):
        return {"ok": False, "msg": "这一箱已经挑过了"}
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (b["tier"],))
    opts = []
    for o in (rnd.get("pick_options") or []):
        c = item_by_code(str(o.get("code", "")))
        if c:
            opts.append(c)
    if not opts:
        return {"ok": False, "msg": "候选已经失效，让系统替你开吧"}
    if auto or not codes:
        codes = [c["code"] for c in opts[:max(1, int(rnd.get("qty", 1) or 1))]]
    given = _grant_pick_cards(member_id, rnd, [str(x) for x in codes], opts, t, box_id,
                              cycle_id=b["cycle_id"], operator_id=operator_id)
    if not given:
        return {"ok": False, "msg": "挑的这几张不对，重新挑一下"}
    db.execute("UPDATE box_open SET random_json=? WHERE id=?",
               (json.dumps(rnd, ensure_ascii=False), box_id))
    return {"ok": True, "box_id": box_id, "tier": b["tier"], "name": t["name"],
            "given": given, "picked": rnd["picked"]}


def _pending_row(b, state, rnd=None):
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (b["tier"],))
    name = t["name"] if t else ("第 %d 档" % b["tier"])
    rnd = rnd or {}
    return {"box_id": b["id"], "tier": b["tier"], "state": state,
            "name": name, "icon": (t["icon"] if t else "") or "",
            "source": b["source"], "threshold": t["threshold"] if t else 0,
            "ts": b["ts"], "cycle_id": b["cycle_id"],
            "need": rnd.get("qty") if state == "unpicked" else None,
            # 开了、自选没挑完的那只：候选跟着这一行一起给出去。孩子点提醒卡
            # 是「接着挑」，不该再往 /open 那条路走（那箱已经算开过了）。
            "options": (rnd.get("pick_options") or []) if state == "unpicked" else []}


def pending_boxes(member_id):
    """还没处理完的箱子，两种都算：

      unopened  压根没点开的（结算发下来躺在那里）
      unpicked  开了、但随机件是自选、那几张还没挑的（孩子开箱开一半退出了）

    正常最多各 1 只 —— 结算一周期发一只，自选一箱只有一处。
    """
    out = []
    for b in db.query("SELECT * FROM box_open WHERE member_id=? AND opened_at IS NULL"
                      " ORDER BY id", (member_id,)):
        out.append(_pending_row(b, "unopened"))
    for b in db.query("SELECT * FROM box_open WHERE member_id=? AND opened_at IS NOT NULL"
                      " ORDER BY id DESC LIMIT 5", (member_id,)):
        rnd = json.loads(b["random_json"] or "{}")
        if rnd.get("pick_required") and not rnd.get("picked"):
            out.append(_pending_row(b, "unpicked", rnd))
    return out


def auto_open_stale(member_id, before_day=None, operator_id=None):
    """把一直没开的箱子替孩子开掉。

    搭在 settle_cycle 上跑（下个周期结算时顺手来一遍），不另起一个定时任务 ——
    跟着「结算」这个已经存在的节拍走，就不会多出一个没人盯着、悄悄失效的调度。
    任务奖励发的箱子没有绑周期，所以这里按 ts 查，不按 cycle_id 查。

    before_day 是正在结算那个周期的 start_date：ts 早于它的箱子，说明隔了至少
    一个完整周期没动，这次结算顺手开掉；本周期新发的箱子不会被误伤。

    两类都收：还没点开的，和点开了、自选没挑完的。系统替孩子开的照发不回收，
    并且留下一条通知（「系统自己动手的事都要留下自己的名字」）。
    """
    before = (before_day or today()) + " 00:00:00"
    out = []
    for b in db.query("SELECT * FROM box_open WHERE member_id=? AND opened_at IS NULL"
                      " AND ts<? ORDER BY id", (member_id, before)):
        r = open_box(member_id, b["id"], auto=True, operator_id=operator_id)
        if r.get("ok"):
            out.append({"box_id": b["id"], "tier": b["tier"], "state": "unopened",
                        "name": r.get("name", ""), "given": r.get("given", [])})
    for b in db.query("SELECT * FROM box_open WHERE member_id=? AND opened_at IS NOT NULL"
                      " AND opened_at<? ORDER BY id", (member_id, before)):
        rnd = json.loads(b["random_json"] or "{}")
        if not (rnd.get("pick_required") and not rnd.get("picked")):
            continue
        r = resolve_box_pick(member_id, b["id"], [], auto=True, operator_id=operator_id)
        if r.get("ok"):
            out.append({"box_id": b["id"], "tier": b["tier"], "state": "unpicked",
                        "name": r.get("name", ""), "given": r.get("given", [])})
    if out:
        push_notify(member_id, "box_auto", "替你开了 %d 只箱子" % len(out),
                    "一直没开的宝箱，系统按「优先给你还没有的」替你开了，东西已经到手上。")
    return out


def buy_box(member_id, tier, operator_id=None):
    """直购箱：不看本周成绩，随时可买，永远比打出来贵。

    v24 起只有金 / 钻石 / 王者三档挂价签（木铜银门槛太低，摆出来会让
    「每天那七分」看起来可以绕过去；完美箱是满勤专属，不卖）。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    t = db.query_one("SELECT * FROM box_tier WHERE tier=?", (tier,))
    if not t:
        return {"ok": False, "msg": "没有这一档宝箱"}
    if not t["purchase_allowed"] or not t["purchase_price"]:
        return {"ok": False, "msg": "%s 不零售，只能靠自己打出来" % t["name"]}
    cyc = current_cycle(member_id)
    limit = int(db.cfg("box.purchase_weekly_limit", 1))
    used = db.query_one("SELECT COUNT(*) c FROM box_open WHERE member_id=? AND cycle_id=?"
                        " AND source='purchase'", (member_id, cyc["id"]))["c"]
    if used >= limit:
        return {"ok": False, "msg": "本周期已经买过 %d 个了" % limit}
    price = t["purchase_price"]
    bal = stardust_balance(member_id)
    if bal < price:
        return {"ok": False, "msg": "星尘不够，还差 %g" % round(price - bal, 2)}
    add_ledger(member_id, "box_purchase", cycle_id=cyc["id"], stardust=-price,
               note="直购 %s" % t["name"], operator_id=operator_id)
    # 付完星尘当场开。直购箱本来就不出随机件、没有悬念，花出去的星尘买的就是
    # 立刻的结果，再让他点一次「打开」没必要（前端接同一段开箱动画）。
    made = issue_box(member_id, tier, cycle_id=cyc["id"], source="purchase",
                     operator_id=operator_id, cost=price)
    if not made or not made.get("ok"):
        return made or {"ok": False, "msg": "买不了"}
    return open_box(member_id, made["box_id"], operator_id=operator_id)


# ---------------------------------------------------------------------------
# 商店
# ---------------------------------------------------------------------------
def _weekly_bought(member_id, item_id, kind, cycle_id):
    """本周期在这条通道上买入的数量（只看正数，消耗不算）。"""
    return db.query_one(
        "SELECT COALESCE(SUM(CASE WHEN li.qty_delta>0 THEN li.qty_delta ELSE 0 END),0) v"
        " FROM ledger_item li JOIN ledger l ON l.id=li.ledger_id"
        " WHERE li.member_id=? AND li.item_id=? AND l.kind=? AND l.cycle_id=?",
        (member_id, item_id, kind, cycle_id))["v"]


def buy_ticket(member_id, code, qty=1, operator_id=None):
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    it = item_by_code(code)
    if not it or it["category"] != "ticket":
        return {"ok": False, "msg": "没有这种券"}
    if not it["purchasable"]:
        return {"ok": False, "msg": "%s 不卖，只能挣出来" % it["name"]}
    qty = int(qty or 1)
    if qty <= 0:
        return {"ok": False, "msg": "数量不对"}
    cyc = current_cycle(member_id)
    if it["weekly_limit"]:
        got = _weekly_bought(member_id, it["id"], "shop_ticket", cyc["id"])
        if got + qty > it["weekly_limit"]:
            return {"ok": False, "msg": "%s 每周限购 %d 张，本周已买 %g 张" %
                                       (it["name"], it["weekly_limit"], got)}
    cost = int(it["price"]) * qty
    bal = stardust_balance(member_id)
    if bal < cost:
        return {"ok": False, "msg": "星尘不够，还差 %g" % round(cost - bal, 2)}
    add_ledger(member_id, "shop_ticket", cycle_id=cyc["id"], stardust=-cost,
               note="购买 %s ×%d" % (it["name"], qty), operator_id=operator_id)
    grant_item(member_id, it["id"], qty, source="shop", kind="shop_ticket", cycle_id=cyc["id"],
               note="购买 %s ×%d" % (it["name"], qty), operator_id=operator_id)
    return {"ok": True, "cost": cost, "balance": stardust_balance(member_id)}


def buy_card(member_id, code, operator_id=None):
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    it = item_by_code(code)
    if not it or it["category"] != "card":
        return {"ok": False, "msg": "没有这张卡"}
    if not it["purchasable"] or not it["price"]:
        return {"ok": False, "msg": "%s 永不售卖，只能从宝箱里开出来" % it["name"]}
    cyc = current_cycle(member_id)
    limit = int(db.cfg("card.weekly_limit", 1))
    got = _weekly_bought(member_id, it["id"], "shop_card", cyc["id"])
    if got + 1 > limit:
        return {"ok": False, "msg": "%s 每周限购 %d 张，本周已买 %g 张" % (it["name"], limit, got)}
    if it["max_hold"] and item_balance(member_id, it["id"]) >= it["max_hold"]:
        return {"ok": False, "msg": "%s 已经持有 %d 张了。买来的卡不拆碎片，先把旧的用掉"
                                   % (it["name"], it["max_hold"])}
    cost = int(it["price"])
    bal = stardust_balance(member_id)
    if bal < cost:
        return {"ok": False, "msg": "星尘不够，还差 %g" % round(cost - bal, 2)}
    add_ledger(member_id, "shop_card", cycle_id=cyc["id"], stardust=-cost,
               note="购买 %s" % it["name"], operator_id=operator_id)
    grant_item(member_id, it["id"], 1, source="shop", kind="shop_card", cycle_id=cyc["id"],
               auto_fragment=False, note="购买 %s" % it["name"], operator_id=operator_id)
    return {"ok": True, "cost": cost, "balance": stardust_balance(member_id)}


# ---------------------------------------------------------------------------
# 星尘出口：兑换零花钱
# ---------------------------------------------------------------------------
def month_cash_used(member_id, ym=None):
    ym = ym or today()[:7]
    return round(db.query_one(
        "SELECT COALESCE(SUM(-delta_stardust),0) v FROM ledger WHERE member_id=? AND voided=0"
        " AND kind='cash_exchange' AND substr(ts,1,7)=?", (member_id, ym))["v"], 2)


def exchange_cash(member_id, stardust, operator_id=None):
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    stardust = float(stardust)
    if stardust <= 0:
        return {"ok": False, "msg": "数量不对"}
    cap = float(db.cfg("cash.monthly_cap_stardust", 60))
    used = month_cash_used(member_id)
    if used + stardust > cap:
        return {"ok": False, "msg": "本月还能兑 %g 星尘（上限 %g 星尘 / %g 元）" %
                                   (max(0.0, cap - used), cap, cap * float(db.cfg("rate.stardust_to_cash", 0.5)))}
    if stardust_balance(member_id) < stardust:
        return {"ok": False, "msg": "星尘不够"}
    rate = float(db.cfg("rate.stardust_to_cash", 0.5))
    pay = round(stardust * rate, 2)
    lid = add_ledger(member_id, "cash_exchange", stardust=-stardust,
                     note="兑换零花钱 %g 元" % pay, operator_id=operator_id)
    # 零花钱加倍卡：翻倍，但多出来的部分封顶（默认 20 星尘等值 = 10 元）。
    # 不封顶的话孩子会把这张卡攒到一次兑 60 星尘那天用，多拿 30 元，
    # 比满勤一周还多 —— 卡的价值就不该超过努力。加成不入月度额度，
    # 它是卡片给的，不是他自己换出来的额度。
    bonus = 0.0
    da = consume_armed(member_id, "double_allowance")
    if da:
        cap = float(da.get("stardust", 20) or 0) * rate
        bonus = round(min(pay, cap), 2)
        if bonus > 0:
            add_ledger(member_id, "cash_bonus", operator_id=operator_id,
                       note="零花钱加倍卡：多 %g 元" % bonus, meta={"cash_bonus": bonus})
    cash = round(pay + bonus, 2)
    return {"ok": True, "cash": cash, "base": pay, "bonus": bonus,
            "doubled": bool(da), "balance": stardust_balance(member_id),
            "month_used": month_cash_used(member_id), "ledger_id": lid}


# ---------------------------------------------------------------------------
# 零花钱兑换：孩子发起 → 家长审核 → 孩子确认收到（v24）
# ---------------------------------------------------------------------------
# 为什么中间要加一道家长审核：星尘是系统里的数，现金是爸妈口袋里的钱。
# 原来的做法是孩子点一下、系统扣星尘，然后「给钱」这件事发生在屏幕上，
# 没人在现实里做过。加这一道不是为了审批（额度已经在设置里卡死了），
# 是让「谁在哪天把多少钱给到了他手上」有个凭据，两边对得上账。
CASH_STATUS = {"pending": "等爸爸妈妈看", "approved": "已发放，等确认",
               "received": "已收到", "rejected": "没批", "cancelled": "已撤回"}


def cash_pending_stardust(member_id):
    """还在审的那几条一共占着多少星尘。额度是按月算的，
    没批的也得占着，否则孩子连提十条把一个月额度用完再逐条批。"""
    r = db.query_one("SELECT COALESCE(SUM(stardust),0) v FROM cash_request"
                     " WHERE member_id=? AND status='pending'", (member_id,))
    return round(float(r["v"] or 0), 2)


def cash_request_view(r, rate=None):
    rate = float(rate if rate is not None else db.cfg("rate.stardust_to_cash", 0.5))
    d = dict(r)
    d["cash"] = round(float(r["cash"] or 0), 2)
    d["est_cash"] = round(float(r["stardust"] or 0) * rate, 2)
    d["status_text"] = CASH_STATUS.get(r["status"], r["status"])
    d["name"] = member_name_of(r["member_id"])
    return d


def request_cash(member_id, stardust, note="", operator_id=None):
    """孩子发起兑换。这一步只登记，不动账 —— 星尘在家长点同意时才扣。

    发起时把「手上够不够」和「本月额度还剩多少」都查一遍，是为了当场告诉他
    行不行，而不是让他等半天再收一句「星尘不够」。真正的扣减仍在审批那一步
    重查一次（中间他可能把钱花掉了）。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    try:
        stardust = round(float(stardust), 2)
    except (TypeError, ValueError):
        return {"ok": False, "msg": "数量不对"}
    if stardust <= 0:
        return {"ok": False, "msg": "数量不对"}
    rate = float(db.cfg("rate.stardust_to_cash", 0.5))
    cap = float(db.cfg("cash.monthly_cap_stardust", 60))
    used = month_cash_used(member_id)
    hold = cash_pending_stardust(member_id)
    if used + hold + stardust > cap:
        return {"ok": False, "msg": "本月还能兑 %g 星尘（%g 元）。上限 %g 星尘 / %g 元，"
                                   "已经在审的也算在里面"
                                   % (max(0.0, cap - used - hold),
                                      max(0.0, cap - used - hold) * rate, cap, cap * rate)}
    if stardust_balance(member_id) < stardust:
        return {"ok": False, "msg": "星尘不够"}
    rid = db.execute(
        "INSERT INTO cash_request (member_id, stardust, cash, status, note, created_at, operator_id)"
        " VALUES (?,?,0,'pending',?,?,?)", (member_id, stardust, (note or "").strip(), now(), operator_id))
    est = round(stardust * rate, 2)
    push_notify(None, "cash", "%s 想换 %g 元零花钱" % (member_name_of(member_id), est),
                "要扣 %g 星尘。同意就当场发放。" % stardust)
    return {"ok": True, "request_id": rid, "stardust": stardust, "est_cash": est,
            "status": "pending", "msg": "提上去了，等爸爸妈妈看一眼"}


def resolve_cash_request(rid, approve, operator_id=None, reject_note=""):
    """家长审核。同意就等于执行发放：当场扣星尘、记流水、记下给了多少钱。

    发放前把余额和额度重查一遍。查不过不是「静默失败」——
    把这条申请标成没批，理由写进去，孩子看得到，不用家长再解释一遍。
    """
    r = db.query_one("SELECT * FROM cash_request WHERE id=?", (rid,))
    if not r:
        return {"ok": False, "msg": "没有这条申请"}
    # 权限读库，不认调用方说什么。接口层已经挡了一道，但引擎是这个流程里
    # 唯一真正扣钱的地方，自己也得看一眼 —— 少一道，某天多一个直接调它的
    # 入口，孩子就能把自己提的兑换批掉。
    if operator_id is not None and not is_judge(operator_id):
        return {"ok": False, "msg": "这一步得家长来点"}
    if r["status"] != "pending":
        return {"ok": False, "msg": "这条已经处理过了（%s）" % CASH_STATUS.get(r["status"], r["status"])}
    child = r["member_id"]

    if not approve:
        if not (reject_note or "").strip():
            return {"ok": False, "msg": "不同意要说一句为什么，他看得到"}
        db.execute("UPDATE cash_request SET status='rejected', reject_note=?, resolved_at=?,"
                   " resolved_by=?, operator_id=? WHERE id=?",
                   (reject_note.strip(), now(), operator_id, operator_id, rid))
        push_notify(child, "cash", "这次兑换没批", reject_note.strip())
        return {"ok": True, "status": "rejected"}

    res = exchange_cash(child, r["stardust"], operator_id=operator_id)
    if not res.get("ok"):
        why = res.get("msg", "兑不了")
        db.execute("UPDATE cash_request SET status='rejected', reject_note=?, resolved_at=?,"
                   " resolved_by=?, operator_id=? WHERE id=?",
                   ("点同意时没兑成：" + why, now(), operator_id, operator_id, rid))
        push_notify(child, "cash", "这次兑换没成", why)
        return {"ok": False, "msg": why}

    cash = res["cash"]
    db.execute("UPDATE cash_request SET status='approved', cash=?, bonus=?, ledger_id=?,"
               " resolved_at=?, resolved_by=?, operator_id=? WHERE id=?",
               (cash, res.get("bonus", 0), res.get("ledger_id"), now(), operator_id, operator_id, rid))
    push_notify(child, "cash", "兑换批了，%g 元" % cash,
                "找爸爸妈妈拿现金，拿到点一下「收到了」。")
    return {"ok": True, "status": "approved", "cash": cash, "bonus": res.get("bonus", 0),
            "balance": res.get("balance"), "ledger_id": res.get("ledger_id")}


def receive_cash_request(rid, member_id, operator_id=None):
    """孩子确认拿到现金，这一条算完结。"""
    r = db.query_one("SELECT * FROM cash_request WHERE id=?", (rid,))
    if not r:
        return {"ok": False, "msg": "没有这条申请"}
    if r["member_id"] != member_id:
        return {"ok": False, "msg": "这条不是你的"}
    if r["status"] == "received":
        return {"ok": False, "msg": "已经确认过了"}
    if r["status"] != "approved":
        return {"ok": False, "msg": "还没发放，等他批了再确认"}
    db.execute("UPDATE cash_request SET status='received', received_at=? WHERE id=?",
               (now(), rid))
    push_notify(None, "cash", "%s 确认收到了 %g 元" % (member_name_of(member_id), r["cash"]),
                "这一条算完结。")
    return {"ok": True, "status": "received", "cash": round(float(r["cash"] or 0), 2)}


def cancel_cash_request(rid, member_id):
    """孩子自己撤回。只撤还没批的，已经发出去的钱不能撤。"""
    r = db.query_one("SELECT * FROM cash_request WHERE id=?", (rid,))
    if not r:
        return {"ok": False, "msg": "没有这条申请"}
    if r["member_id"] != member_id and not is_judge(member_id):
        return {"ok": False, "msg": "这条不是你的"}
    if r["status"] != "pending":
        return {"ok": False, "msg": "已经处理过了，撤不了"}
    db.execute("UPDATE cash_request SET status='cancelled', resolved_at=?, operator_id=? WHERE id=?",
               (now(), member_id, rid))
    return {"ok": True, "status": "cancelled"}


def cash_request_list(member_id=None, limit=30):
    if member_id is None:
        rows = db.query("SELECT * FROM cash_request ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.query("SELECT * FROM cash_request WHERE member_id=? ORDER BY id DESC LIMIT ?",
                        (member_id, limit))
    rate = float(db.cfg("rate.stardust_to_cash", 0.5))
    return [cash_request_view(r, rate) for r in rows]


def pending_cash_count():
    return db.query_one("SELECT COUNT(*) c FROM cash_request WHERE status='pending'")["c"]


# ---------------------------------------------------------------------------
# 校准（三层）
# ---------------------------------------------------------------------------
def add_calibration(member_id, level, reason, *, dimension_code=None, effect_type="none",
                    amount=0, template=None, operator_id=None, auto_task=True,
                    repair_std=None):
    """level 1 自校准 / 2 联动校准 / 3 契约校准。"""
    if not (reason or "").strip():
        return {"ok": False, "msg": "校准必须写清楚是哪件事"}
    dim_id = None
    if dimension_code:
        d = db.query_one("SELECT id FROM dimension WHERE code=?", (dimension_code,))
        dim_id = d["id"] if d else None

    effect = {}
    task_id = None
    if effect_type == "fine":
        # 单次金额上限：孩子与家长同额，不叠加、不翻倍（第 08 章）。
        # 传大了要截断，否则「自愿双倍自罚」会被接口当成默认行为。
        top = float(db.cfg("calib.fine_amount", 5))
        cash = min(float(amount or top), top)
        per = top or 5.0
        sd = round(cash / per * float(db.cfg("calib.fine_to_stardust", 10)), 2)
        bal = stardust_balance(member_id)
        take = min(bal, sd)
        rest = round(sd - take, 2)
        if take > 0:
            add_ledger(member_id, "fine", stardust=-take, note="契约校准罚款 %g 元" % cash,
                       operator_id=operator_id, meta={"reason": reason})
        if rest > 0:
            add_ledger(member_id, "fine", debt=rest, note="余额不足，记欠款 %g 星尘" % rest,
                       operator_id=operator_id, meta={"reason": reason})
        pool = active_pool()
        if pool:
            db.execute("INSERT INTO wish_pool_entry (pool_id, member_id, source, stardust, cash,"
                       " note, ts) VALUES (?,?,'fine',?,?,?,?)",
                       (pool["id"], member_id, sd, cash, "罚款入池：" + reason, now()))
        effect = {"stardust": sd, "cash": cash, "debt": rest}
    elif effect_type == "ticket_min":
        # 两道强度上限（第 08 章，唯一口径）：
        #   单日最多 −30 分钟，超出的不再累加；
        #   券包最低记到 −60 分钟，再往下不累加，避免「反正已经欠很多了」的放弃心态。
        want = float(amount or db.cfg("calib.ticket_min", 15))
        # 这两个设置存的是负数（-30 / -60），读进来取绝对值当上限用
        daily_cap = abs(float(db.cfg("calib.daily_ticket_min", 30)))
        floor = abs(float(db.cfg("calib.debt_floor_min", 60)))
        minutes = max(0.0, min(want, daily_cap - minutes_debt_today(member_id)))
        minutes = max(0.0, min(minutes, floor - minutes_debt(member_id)))
        effect = {"minutes": minutes, "want": want, "capped": minutes < want,
                  "note": ("已到强度上限，这次不再往下扣" if minutes < want else "")}
        if minutes > 0:
            add_ledger(member_id, "fine", day=today(), minutes=-minutes,
                       note="校准扣减 %g 分钟" % minutes,
                       operator_id=operator_id, meta={"reason": reason})
    elif effect_type == "task" and auto_task:
        # 后果自选卡：校准照走，但修复方式由孩子自己写。规则里这条写着
        # 「爸爸妈妈不能替你指定」，所以这里连 template 都不代挑，
        # 完成标准换成让他自己提方案。
        own = bool(consume_armed(member_id, "choose_consequence"))
        tpl = template or "redo"
        # repair_std：家长自己写的那条修复方式（不是四选一里挑的）。
        # 传下来就当完成标准用，任务里写的是他写的那句话；
        # 不传的话才由 template 去查预设 —— 自定义那条别被预设吞掉。
        task_id = create_repair_task(member_id, reason, template=tpl, std=repair_std,
                                     operator_id=operator_id, own_choice=own)
        effect = {"task_id": task_id, "template": "own" if own else tpl, "own_choice": own}
    elif effect_type == "device":
        effect = {"detail": "设备改到公共区域使用，3 天后自动恢复"}

    cid = db.execute(
        "INSERT INTO calibration (member_id, level, dimension_id, reason, effect_type, effect_json,"
        " amount, operator_id, ts) VALUES (?,?,?,?,?,?,?,?,?)",
        (member_id, level, dim_id, reason, effect_type,
         json.dumps(effect, ensure_ascii=False), amount, operator_id, now()))

    if task_id:
        db.execute("UPDATE task SET calibration_id=? WHERE id=?", (cid, task_id))

    # 反升级：同一维度 30 天内达到阈值，提示技能缺口（不加罚）
    hint = None
    th = int(db.cfg("anti_escalation.threshold", 5))
    if dim_id:
        n = db.query_one(
            "SELECT COUNT(*) c FROM calibration WHERE member_id=? AND dimension_id=?"
            " AND ts >= ?", (member_id, dim_id,
                             fmt(parse_day(today()) - timedelta(days=30))))["c"]
        if n >= th:
            # 同一条提示 90 天内只弹一次，第二次触发换一句话。
            # 不加这一条，卫生这种高频维度会每周弹同一句，提醒就变成唠叨了。
            gap = int(db.cfg("anti_escalation.hint_cooldown_days", 90))
            key = "anti_hint:%d:%d" % (member_id, dim_id)
            last = db.query_one("SELECT value FROM meta WHERE key=?", (key,))
            if not last or (parse_day(today()) - parse_day(last["value"][:10])).days >= gap:
                cnt_key = "anti_hint_n:%d:%d" % (member_id, dim_id)
                prev = db.query_one("SELECT value FROM meta WHERE key=?", (cnt_key,))
                times = int(prev["value"]) + 1 if prev else 1
                dim_name = db.query_one("SELECT name FROM dimension WHERE id=?", (dim_id,))
                dim_name = dim_name["name"] if dim_name else "这一项"
                if times == 1:
                    hint = ("〈%s〉30 天内出现 %d 次，可能是习惯或工具的问题。"
                            "要不要一起看看卡在哪？换个做法：视觉提示卡、提前 10 分钟闹铃、"
                            "把东西放在最显眼的位置、减少步骤。" % (dim_name, n))
                else:
                    hint = "〈%s〉这一项要不要调一下标准？" % dim_name
                for k, v in ((key, today()), (cnt_key, str(times))):
                    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (k, v))
                push_notify(None, "anti_escalation", "反升级提醒", hint)
    return {"ok": True, "calibration_id": cid, "task_id": task_id, "effect": effect, "hint": hint}


# ---------------------------------------------------------------------------
# 任务清单（奖励任务 + 系统生成的修复任务）
# ---------------------------------------------------------------------------
def create_repair_task(member_id, reason, *, template="redo", std=None, operator_id=None,
                       calibration_id=None, own_choice=False):
    hours = {"apology": 24, "goods": 48, "redo": 0, "relation": 48}.get(template, 48)
    if own_choice:
        # 「含糊不得」那条原则在这里的写法：标准必须是看得懂、能核对的，
        # 让孩子自己提也一样 —— 他得写清楚打算做什么，爸爸妈妈才好确认。
        std = "这件事你打算怎么补，自己写下来交给爸爸妈妈确认。" \
              "写清楚具体做什么、什么时候做完（关于：%s）" % reason
        hours = 48
    preset = {r[0]: r for r in json.loads(
        db.query_one("SELECT value FROM setting WHERE key='repair.templates'")["value"])}
    tpl = preset.get(template, ("", "修复任务", hours, reason, reason))
    title = "%s：%s" % (tpl[1], reason)
    standard = std or tpl[4]
    deadline = None
    if hours:
        deadline = (_dtnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    return db.execute(
        "INSERT INTO task (kind, title, std, assignee_id, created_by, reward_type, deadline,"
        " status, visibility, template, calibration_id, icon, created_at) "
        "VALUES ('repair',?,?,?,?,'',?,'pending','private',?,?,?,?)",
        (title, standard, member_id, operator_id, deadline, template, calibration_id,
         "sys_repair", now()))


def default_claim_deadline(hours=None):
    """大厅任务的默认接取时限。

    发布时没填截止时间，就按 task.claim_deadline_hours 往后推一个。
    「接取时限」只管接取这一层：到点还没人接，由家长自己撤下 —— 系统不会
    自动下线一条任务（那条刻意不做，见开发文档第 9 节）。所以这里做的
    只是「让家长不填也有个数」，不是给系统装一个定时器。

    填 0 或负数 = 不给默认值，存 NULL（前端显示成「不限」）。
    """
    if hours is None:
        hours = int(db.cfg("task.claim_deadline_hours", 48) or 0)
    if hours <= 0:
        return None
    return (_dtnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def create_task(assignee_id, title, std, reward_type="stardust", reward=None, deadline=None,
                created_by=None, visibility="family", slots=1, icon="", cooldown_key=""):
    """发一条奖励任务。

    assignee_id 为 None 时挂进任务大厅：状态 open，谁都能看见、谁都能来领。
    slots 只对大厅任务有意义，1 = 先到先得，0 = 每个孩子各一份。
    icon 是可选的显示层装饰，不影响任何数值；留空由前端按类型回落。
    cooldown_key 非空时，同一 key 在本周期内只能发布一条（第 12 章护栏五）。
    """
    reward = reward if isinstance(reward, dict) else {}
    icon = clean_icon(icon)
    title = (title or "").strip()
    std = (std or "").strip()
    if not title:
        return {"ok": False, "msg": "任务要有标题"}
    if not std:
        return {"ok": False, "msg": "完成标准要能一眼核对，别留空"}

    # 护栏四、五：宝箱只到银箱、道具卡只到普通级、单条奖励的额度上限。
    # 这几条与「派给谁」无关，大厅任务一样要过 —— 挂在 assignee_id 判断后面，
    # 等于「挂到大厅就能发传说中的东西」。
    if reward_type == "box":
        max_tier = int(db.cfg("task.box_max_tier", 3))
        if int(reward.get("tier", max_tier) or 0) > max_tier:
            return {"ok": False, "msg": "任务奖励宝箱最多到第 %d 档（银箱）" % max_tier}
        if int(reward.get("tier", max_tier) or 0) < 1:
            return {"ok": False, "msg": "宝箱档位不对"}
    if reward_type == "card":
        if (reward.get("rarity") or "common") != db.cfg("task.card_max_rarity", "common"):
            return {"ok": False, "msg": "任务奖励道具卡最多到普通级"}
        it = item_by_code(reward.get("code", "company_card"))
        if not it or it["category"] != "card":
            return {"ok": False, "msg": "没有这张卡"}
    if reward_type == "ticket":
        qty = float(reward.get("qty", 1) or 0)
        if not 1 <= qty <= 3:
            return {"ok": False, "msg": "任务奖励的券是 1 到 3 张"}
    if reward_type == "stardust":
        amt = float(reward.get("amount", 1) or 0)
        if not 0 < amt <= 10:
            return {"ok": False, "msg": "任务奖励星尘是 1 到 10"}
    if reward_type == "energy":
        amt = float(reward.get("amount", 1) or 0)
        if not 0 < amt <= 3:
            return {"ok": False, "msg": "任务奖励周能量是 1 到 3 分"}
    if reward_type not in ("stardust", "energy", "ticket", "card", "box", "goods", "privilege"):
        return {"ok": False, "msg": "不认识的奖励类型"}

    # 护栏五（第 12 章）：同类任务有冷却，本周期内同种任务不重复发布。
    key = (cooldown_key or "").strip()
    if key:
        start = week_start_of(today())
        dup = db.query_one(
            "SELECT id FROM task WHERE kind='reward' AND cooldown_key=? AND status NOT IN"
            " ('cancelled','archived','abandoned') AND created_at>=?", (key, start))
        if dup:
            return {"ok": False, "msg": "本周期已经发过同一类任务了（%s）" % key}

    if assignee_id is None:
        # 大厅任务这会儿还不知道谁做，星尘上限等领取那一刻再查
        # （见 _task_reward_blocked）。发布时根本没人可以挂上限。
        # 接取时限也在这里兜底：不填就从设置里取一个，只有大厅任务需要它 ——
        # 指名派下去的任务已经有主人，没有「等着谁来接」这一层。
        # deadline 三种取值要分开认：
        #   None  = 家长没选，按设置给一个默认值；
        #   ''    = 家长选了「不限时」，存 NULL（不进过期清理，前端显示成「不限」）；
        #   其余  = 家长指定的那一天。
        # 原来只有「有就用、没有就用默认」两路，选了「不限时」会被默认 48 小时顶回来。
        if deadline is None:
            deadline = default_claim_deadline()
        elif deadline == "":
            deadline = None
        return db.execute(
            "INSERT INTO task (kind, title, std, assignee_id, created_by, reward_type, reward_json,"
            " deadline, status, visibility, slots, icon, cooldown_key, created_at)"
            " VALUES ('reward',?,?,NULL,?,?,?,?,'open',?,?,?,?,?)",
            (title, std, created_by, reward_type,
             json.dumps(reward, ensure_ascii=False), deadline, visibility,
             0 if slots in (None, 0) else int(slots), icon, key, now()))
    if not is_player(assignee_id):
        return {"ok": False, "msg": PARENT_MSG}
    cyc = current_cycle(assignee_id)
    # 护栏：任务奖励星尘每周 ≤20
    if reward_type == "stardust":
        cap = float(db.cfg("task.stardust_weekly_cap", 20))
        used = db.query_one(
            "SELECT COALESCE(SUM(CAST(json_extract(reward_json,'$.amount') AS REAL)),0) v FROM task"
            " WHERE assignee_id=? AND kind='reward' AND status IN ('confirmed','submitted')"
            " AND created_at>=?", (assignee_id, cyc["start_date"]))["v"]
        amt = float(reward.get("amount", 1))
        if used + amt > cap:
            return {"ok": False, "msg": "本周任务星尘已达上限 %g（已 %g）" % (cap, used)}
    return db.execute(
        "INSERT INTO task (kind, title, std, assignee_id, created_by, reward_type, reward_json,"
        " deadline, status, visibility, slots, icon, cooldown_key, created_at)"
        " VALUES ('reward',?,?,?,?,?,?,?,'pending',?,1,?,?,?)",
        (title, std, assignee_id, created_by, reward_type,
         json.dumps(reward, ensure_ascii=False), deadline, visibility, icon, key, now()))


def _task_reward_blocked(member_id, p):
    """领一个大厅任务之前，按他的周额度查一遍。

    发布时还不知道谁做，上限只能挪到这一刻查。查不过就别让他领，
    免得领回来一堆完不成、家长一点确认又被护栏挡下。
    """
    if p["reward_type"] != "stardust":
        return ""
    cyc = current_cycle(member_id)
    if not cyc:
        return ""
    cap = float(db.cfg("task.stardust_weekly_cap", 20))
    used = db.query_one(
        "SELECT COALESCE(SUM(CAST(json_extract(reward_json,'$.amount') AS REAL)),0) v FROM task"
        " WHERE assignee_id=? AND kind='reward' AND status IN ('confirmed','submitted')"
        " AND created_at>=?", (member_id, cyc["start_date"]))["v"]
    amt = float(json.loads(p["reward_json"] or "{}").get("amount", 1))
    if used + amt > cap:
        return "本周任务星尘已达上限 %g（已 %g）" % (cap, used)
    return ""


def submit_task(task_id, member_id=None):
    t = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    # claimed = 自己从大厅领的；pending = 家长直接派的。两者都能交。
    if t["status"] not in ("pending", "claimed"):
        return {"ok": False, "msg": "这个任务现在的状态不能提交"}
    db.execute("UPDATE task SET status='submitted', submitted_at=? WHERE id=?", (now(), task_id))
    push_notify(None, "task_submitted", "有待确认的任务", t["title"])
    return {"ok": True, "task_id": task_id, "status": "submitted"}


def confirm_task(task_id, operator_id=None, auto=False):
    t = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    if t["status"] not in ("submitted", "pending", "claimed"):
        return {"ok": False, "msg": "这个任务现在的状态不能确认"}
    given = _pay_task_reward(t, operator_id)
    db.execute("UPDATE task SET status='confirmed', confirmed_at=? WHERE id=?",
               (now(), task_id))
    # 这是从大厅领来的一份，回去把大厅那条的进度也刷一下
    if t["hall_id"]:
        _settle_hall(t["hall_id"])
    if t["assignee_id"]:
        push_notify(t["assignee_id"], "task_confirmed", "这件事成了",
                    "%s%s" % (t["title"], _given_text(given)))
        # 奖励里可能有周能量，周能量一变，心愿进度就可能刚够
        check_wish_ready(t["assignee_id"])
    return {"ok": True, "task_id": task_id, "given": given}


_GIVEN_LABEL = {"stardust": "星尘", "energy": "周能量"}


def _task_item_kind(t):
    """任务发券/发卡时的流水类型：修复任务记 repair，普通任务记 task_item。

    两者在账上都是「发了一件道具」，但对家长来说意思完全不同 ——
    一个是孩子挨了罚要补救，一个是他做成了事拿的奖。日志里混成一个词，
    就等于没说。
    """
    return "repair" if t and t["kind"] == "repair" else "task_item"


def _given_text(given, limit=3):
    """把发出去的东西拼成一句人话，给通知用。

    奖励里的 type 是英文（stardust / energy / ticket），直接拼进通知就是
    往孩子手机上推一句「task_stardust +1」。这里翻一遍。
    """
    if not given:
        return ""
    bits = []
    for g in given[:limit]:
        t = g.get("type")
        if t == "box":
            bits.append("宝箱已发放")
        elif t in ("goods", "privilege"):
            bits.append(g.get("detail") or "线下兑现")
        else:
            label = g.get("name") or _GIVEN_LABEL.get(t, t)
            bits.append("%s +%g" % (label, g["qty"]) if g.get("qty") else str(label))
    tail = "等 %d 项" % len(given) if len(given) > limit else ""
    return ("，" + "、".join(bits) + tail) if bits else ""


def _pay_task_reward(t, operator_id=None):
    if t["kind"] != "reward":
        return []
    r = json.loads(t["reward_json"] or "{}")
    rt = t["reward_type"]
    given = []
    if rt == "stardust":
        amt = float(r.get("amount", 1))
        doubled_ctx = bool(consume_armed(t["assignee_id"], "double_reward"))
        if doubled_ctx:
            amt = amt * 2
        add_ledger(t["assignee_id"], "task_stardust", stardust=amt,
                   note="任务奖励：" + t["title"] + ("（翻倍卡 ×2）" if doubled_ctx else ""),
                   operator_id=operator_id)
        given.append({"type": "stardust", "qty": amt, "doubled": doubled_ctx})
    elif rt == "energy":
        amt = float(r.get("amount", 1))
        cyc = current_cycle(t["assignee_id"])
        # 护栏二（第 12 章）：任务奖励的周能量与星探共用每周 7 分上限，
        # 超出部分自动转星尘。这条不在发布时查、也不在领取时查，
        # 只有发出去这一刻才知道前面已经用了多少。
        keep, overflow = cap_energy(t["assignee_id"], cyc, amt)
        if keep:
            add_ledger(t["assignee_id"], "task_energy", cycle_id=cyc["id"], energy=keep,
                       note="任务奖励：%s（周能量 +%g）" % (t["title"], keep),
                       operator_id=operator_id)
        if overflow:
            add_ledger(t["assignee_id"], "task_energy", cycle_id=cyc["id"], stardust=overflow,
                       note="周能量已满，自动转星尘 %g" % overflow, operator_id=operator_id)
        recalc_cycle(cyc["id"])
        given.append({"type": "energy", "qty": keep, "overflow_stardust": overflow})
    elif rt == "ticket":
        it = item_by_code(r.get("code", "ticket_fun"))
        qty = float(r.get("qty", 1))
        if it:
            grant_item(t["assignee_id"], it["id"], qty, source="task", kind=_task_item_kind(t),
                       note="任务奖励：" + it["name"], operator_id=operator_id)
            given.append({"type": "ticket", "name": it["name"], "qty": qty})
    elif rt == "card":
        it = item_by_code(r.get("code", "company_card"))
        if it:
            grant_item(t["assignee_id"], it["id"], 1, source="task", kind=_task_item_kind(t),
                       note="任务奖励：" + it["name"], operator_id=operator_id)
            given.append({"type": "card", "name": it["name"]})
    elif rt == "box":
        tier = int(r.get("tier", 3))
        box = issue_box(t["assignee_id"], tier, source="free", operator_id=operator_id)
        given.append({"type": "box", "tier": tier, "detail": box})
    elif rt in ("goods", "privilege"):
        given.append({"type": rt, "detail": r.get("desc", "线下兑现，系统记账")})
    return given


def return_task(task_id, operator_id=None, note=""):
    t = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    # 退回到他上一个状态：从大厅领来的回到「在做」，家长直接派的回到「待做」
    back = "claimed" if t["hall_id"] else "pending"
    n = (t["return_count"] or 0) + 1
    db.execute("UPDATE task SET status=?, return_count=?, submitted_at=NULL WHERE id=?",
               (back, n, task_id))
    db.execute("INSERT INTO notification (member_id, kind, title, body, ts) VALUES (?,?,?,?,?)",
               (t["assignee_id"], "task_returned", "这件事还要再做一次", note or t["title"], now()))
    hint = None
    if n >= 2:
        hint = "同一件事被退回第 %d 次，走反升级流程：换方法，别再加罚" % n
        push_notify(None, "anti_escalation", "退回次数提醒", hint)
    return {"ok": True, "return_count": n, "hint": hint}


def archive_due_tasks():
    """提交后超过设定小时数未处理，视为完成（不进逾期）。

    奖励任务读 task.auto_confirm_hours，修复任务读 repair.auto_archive_hours。
    两个设置分开，是因为「家长没点确认」在两个通道里的含义不一样：
    奖励任务拖着，孩子会以为白做了；修复任务拖着，只是记录晚了一点。
    """
    out_rows = []
    for kind, key, dflt in (("reward", "task.auto_confirm_hours", 48),
                            ("repair", "repair.auto_archive_hours", 48)):
        hours = int(db.cfg(key, dflt))
        limit = (_dtnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = db.query("SELECT * FROM task WHERE kind=? AND status='submitted'"
                        " AND submitted_at IS NOT NULL AND submitted_at<=?", (kind, limit))
        for t in rows:
            if kind == "reward":
                _pay_task_reward(t, None)
            db.execute("UPDATE task SET status='confirmed', confirmed_at=?, archived_at=?"
                       " WHERE id=?", (now(), now(), t["id"]))
            if t["hall_id"]:
                _settle_hall(t["hall_id"])
            if t["assignee_id"]:
                check_wish_ready(t["assignee_id"])
        out_rows += rows
    # 修复任务逾期：转契约校准（只罚金，不叠加新任务）
    out = []
    for t in db.query("SELECT * FROM task WHERE kind='repair' AND status IN ('pending','returned')"
                      " AND deadline IS NOT NULL AND deadline<=? AND deadline!=''", (now(),)):
        r = add_calibration(t["assignee_id"], 3, "修复任务逾期：" + t["title"],
                            effect_type="fine", auto_task=False)
        db.execute("UPDATE task SET status='archived', archived_at=? WHERE id=?", (now(), t["id"]))
        out.append({"task_id": t["id"], "calibration": r})
    return {"archived": len(rows), "overdue": out}


# ---------------------------------------------------------------------------
# 任务大厅（v15）
#
# 两条记录两层意思：
#   母记录 —— assignee_id IS NULL，status='open'，只登记「有这么件活儿」，
#             谁做不知道。slots 决定能发几份：1 = 先到先得，0 = 每个孩子各一份。
#   子记录 —— assignee_id 是某个孩子，hall_id 指回母记录，真的在那儿流转。
# 领取 = 生成一条子记录；撤销 = 把母记录下线，前提是没有子记录还活着。
# ---------------------------------------------------------------------------
def _reward_text(reward_type, reward):
    """把奖励翻成一句人话。前端、通知、规则书都吃这一句，别各写各的。"""
    r = reward or {}
    if reward_type == "stardust":
        return "星尘 +%g" % float(r.get("amount", 1))
    if reward_type == "energy":
        return "周能量 +%g" % float(r.get("amount", 1))
    if reward_type == "ticket":
        it = item_by_code(r.get("code", "ticket_fun"))
        return "%s ×%g" % (it["name"] if it else "券", float(r.get("qty", 1)))
    if reward_type == "card":
        it = item_by_code(r.get("code", "company_card"))
        return it["name"] if it else "道具卡"
    if reward_type == "box":
        return "宝箱（第 %d 档）" % int(r.get("tier", 3))
    if reward_type in ("goods", "privilege"):
        return r.get("desc", "线下兑现")
    return r.get("desc", "无奖励")


def _hall_children(hall_id):
    return db.query(
        "SELECT t.*, m.name AS who FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
        " WHERE t.hall_id=? ORDER BY t.id", (hall_id,))


def _hall_derived(hall):
    """围着母记录算一遍：谁在领、领了几个、还有没有位置、能不能撤。

    状态不做冗余存储，全从这里现算，省得两处对不上。
    """
    kids = _hall_children(hall["id"])
    active = [k for k in kids if k["status"] in ("claimed", "submitted")]
    done = [k for k in kids if k["status"] == "confirmed"]
    quit_ = [k for k in kids if k["status"] == "abandoned"]
    slots = hall["slots"] or 0
    full = (slots == 1 and len(active) > 0)
    d = dict(hall)
    d["reward"] = json.loads(hall["reward_json"] or "{}")
    d["reward_text"] = _reward_text(hall["reward_type"], d["reward"])
    d["slots"] = slots
    d["claims"] = [{"task_id": k["id"], "member_id": k["assignee_id"], "who": k["who"],
                    "status": k["status"], "claimed_at": k["claimed_at"]} for k in kids if k["status"] != "abandoned"]
    d["active"] = len(active)
    d["done"] = len(done)
    d["quit"] = len(quit_)
    d["full"] = full
    # 撤不掉的情况要点名人，家长才知道该催谁
    d["blockers"] = [k["who"] for k in active]
    d["can_revoke"] = (hall["status"] == "open" and not active)
    if hall["status"] != "open":
        d["state"] = "done" if done else "revoked"
    elif active:
        d["state"] = "doing"
    else:
        d["state"] = "open"
    return d


def _settle_hall(hall_id):
    """一份做完就下线；每个孩子各一份的留在池里等人接着领。"""
    hall = db.query_one("SELECT * FROM task WHERE id=?", (hall_id,))
    if not hall or hall["status"] != "open":
        return None
    if (hall["slots"] or 0) == 1 and _hall_derived(hall)["done"]:
        db.execute("UPDATE task SET status='archived', archived_at=? WHERE id=?", (now(), hall_id))
    return True


def _doing_row(r, hall_id=None):
    rw = json.loads(r["reward_json"] or "{}")
    d = dict(r)
    d["reward"] = rw
    d["reward_text"] = _reward_text(r["reward_type"], rw)
    d["hall_id"] = hall_id
    return d


def task_hall(viewer=None):
    """任务大厅。家长和孩子看同一份数据，只是各自多几个「我能干嘛」的标记。

    分三组：
      等人领 —— 母记录还开着、并且还留得下位置。先到先得的被人领走就不再出现；
                每个孩子各一份的那条会一直留着，卡片上带着「谁在做」。
      进行中 —— 每一份活记录，谁在做、做到哪一步。
      已结束 —— 下线了的母记录，做完下线还是被撤，看有没有人交成功过。
    """
    archive_due_tasks()
    halls = []
    for hall in db.query("SELECT * FROM task WHERE hall_id IS NULL AND assignee_id IS NULL"
                         " AND kind='reward' ORDER BY id DESC LIMIT 200"):
        d = _hall_derived(hall)
        d["closed"] = hall["status"] != "open"
        d["can_claim"] = (not d["closed"] and not d["full"])
        if viewer:
            # 一个孩子只能领一份。已经领过就别再显示「我要做」，
            # 不然连点两下会领出两条来。
            mine = [k for k in d["claims"] if k["member_id"] == viewer
                    and k["status"] in ("claimed", "submitted")]
            d["mine"] = mine[0] if mine else None
            if d["mine"]:
                d["can_claim"] = False
        halls.append(d)
    # 「进行中」是每一份活记录。大厅领出来的和直接派下去的都在这里，
    # 不然家长看不到孩子手上还压着什么。
    doing = [_doing_row(r, r["hall_id"]) for r in db.query(
        "SELECT t.*, m.name AS who FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
        " WHERE t.kind='reward' AND t.status IN ('claimed','submitted')"
        " ORDER BY CASE t.status WHEN 'submitted' THEN 0 ELSE 1 END, t.id DESC LIMIT 200")]
    doing += [_doing_row(r) for r in db.query(
        "SELECT t.*, m.name AS who FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
        " WHERE t.kind='reward' AND t.hall_id IS NULL AND t.status='pending'"
        " ORDER BY t.id DESC LIMIT 200")]
    return {
        "hall": [d for d in halls if not d["closed"] and not d["full"]],
        "doing": doing,
        "done": [d for d in halls if d["closed"]],
        "mine": [d for d in halls if viewer and d.get("mine")],
    }


def task_claim(task_id, member_id):
    """孩子从大厅领一份。领了就是他的，家长也撤不掉了。"""
    hall = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not hall or hall["hall_id"] is not None or hall["assignee_id"] is not None:
        return {"ok": False, "msg": "大厅里没有这条任务"}
    if hall["status"] != "open":
        return {"ok": False, "msg": "这条已经下线了"}
    d = _hall_derived(hall)
    if d["full"]:
        return {"ok": False, "msg": "已经被 %s 领走了" % (", ".join(d["blockers"]) or "别人")}
    dup = db.query_one("SELECT id FROM task WHERE hall_id=? AND assignee_id=?"
                       " AND status IN ('claimed','submitted')", (task_id, member_id))
    if dup:
        return {"ok": False, "msg": "你已经领过这一件了"}
    blocked = _task_reward_blocked(member_id, hall)
    if blocked:
        return {"ok": False, "msg": blocked}
    tid = db.execute(
        "INSERT INTO task (kind, title, std, assignee_id, created_by, reward_type, reward_json,"
        " deadline, status, visibility, slots, hall_id, claimed_at, icon, created_at)"
        " VALUES ('reward',?,?,?,?,?,?,?,'claimed','family',?,?,?,?,?)",
        (hall["title"], hall["std"], member_id, hall["created_by"], hall["reward_type"],
         hall["reward_json"], hall["deadline"], hall["slots"], task_id, now(),
         hall["icon"], now()))
    push_notify(None, "task_claimed", "有任务被领走了", hall["title"])
    return {"ok": True, "task_id": tid, "status": "claimed"}


def my_task_history(member_id, days=30):
    """孩子自己的任务底账：不管成没成、放没放下，只要经他手就在这儿。

    和 /api/tasks 那条不一样：那条是家长在用的「家庭任务清单」，对孩子只回
    kind='reward'。修复任务也是他做过的事，在那儿看不见，孩子会以为那件事
    没发生过。状态一个不筛：待做、在做、等确认、已完成、被退回、已放弃、
    已撤回，全都带着 —— 这份记录要回答的是「我这些活后来怎么了」。

    只看近 N 天（默认 30）。「最多回溯一个月」是产品口径，不是为了省事：
    再往前的翻起来没意义，也没人在乎三个月前放下的那件事。
    排序按「最后一次动它的时刻」，不是创建时刻 —— 一件派下来躺了两天的活，
    今天交上去，它应该出现在最上面。
    """
    archive_due_tasks()
    since = days_back(days)
    rows = db.query(
        "SELECT t.*, m.name AS assignee,"
        " COALESCE(t.confirmed_at, t.archived_at, t.submitted_at,"
        "          t.claimed_at, t.created_at) AS touched_at"
        " FROM task t LEFT JOIN member m ON m.id=t.assignee_id"
        " WHERE t.assignee_id=? AND t.kind IN ('reward','repair')"
        "   AND COALESCE(t.confirmed_at, t.archived_at, t.submitted_at,"
        "                t.claimed_at, t.created_at) >= ?"
        " ORDER BY touched_at DESC, t.id DESC LIMIT 300", (member_id, since))
    out = []
    for r in rows:
        d = dict(r)
        d["reward"] = json.loads(r["reward_json"] or "{}")
        out.append(d)
    return {"items": out, "days": int(days), "since": since}


def task_abandon(task_id, member_id):
    """孩子主动不做了。回到待领，家长这才能撤销。

    不删记录，标成 abandoned：万一以后想说清「这件当初谁领过又放了」，
    有据可查。各种计数只看活着的记录，所以放着不影响别人领。
    """
    t = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    if t["assignee_id"] != member_id:
        return {"ok": False, "msg": "这不是你的任务"}
    if t["status"] != "claimed":
        return {"ok": False, "msg": "已经交上去了，这时候不能反悔"}
    db.execute("UPDATE task SET status='abandoned', submitted_at=NULL WHERE id=?", (task_id,))
    if t["hall_id"]:
        push_notify(None, "task_abandoned", "有任务被放回来了", t["title"])
    return {"ok": True, "status": "abandoned", "hall_id": t["hall_id"]}


def task_revoke(task_id, operator_id=None):
    """家长撤销。手里还压着活儿的不许撤，得等孩子自己放下。"""
    t = db.query_one("SELECT * FROM task WHERE id=?", (task_id,))
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    if t["status"] in ("confirmed", "archived", "abandoned"):
        return {"ok": False, "msg": "这条已经结束了"}
    if t["hall_id"]:
        return {"ok": False, "msg": "这是从大厅领出来的一份，要撤请去撤大厅那条"}
    if t["assignee_id"] is None:
        d = _hall_derived(t)
        if d["blockers"]:
            return {"ok": False,
                    "msg": "%s 还在做，让他先点「我不做了」才能撤" % "、".join(d["blockers"])}
    elif t["status"] == "submitted":
        return {"ok": False, "msg": "孩子已经交上来了，只能确认或退回"}
    db.execute("UPDATE task SET status='archived', archived_at=? WHERE id=?", (now(), task_id))
    if t["assignee_id"]:
        push_notify(t["assignee_id"], "task_revoked", "有件事不用做了", t["title"])
    return {"ok": True, "status": "archived"}


# ---------------------------------------------------------------------------
# 心愿单
#
# 规则全书第 11 节写的是三个动作：孩子许愿 → 父母设条件 → 达成兑现。
# v16 及以前只实现了「父母建一个已经带条件的心愿」，孩子那一步没地方写，
# 所以「孩子自己许愿」这条唯一的自下而上通道一直是堵的。
# v17 把它补成状态机：
#
#   wished ──家长定条件──→ active ──进度满──→ achieved ──兑现──→ claimed
#      │                      │
#      └──── 驳回／撤回 ───────┴──────→ cancelled
#
# 「挂起」和「进行中」必须是两个状态，不能拿一个字段兼任：
# 前者不占 wish.max_active 名额（条件都没定，谈不上「在努力」），
# 后者才占。混在一起孩子一许愿就顶掉一个正在进行的心愿，他会立刻学会不写。
# ---------------------------------------------------------------------------
#
# v25 加两种形态。前五种是「能算的」，门槛递出去系统就用现成的数据自己往里填；
# 后两种是「算不了的」和「好几条里挑一条的」，各自补了一个短板：
#
#   custom  家长想不出用五个模板里的哪个。以前只能硬凑一个意思差一点的，
#           结果条件名和真实约定对不上，孩子看着进度条走完，家长却说「我说的是另一件事」。
#           自定义那条没有进度条，靠孩子说一声、家长确认，判定权在本来说话的人手里。
#   any     一件事有好几条路能到（这周固定分打满，或者交掉三件任务）。
#           以前只能选一条最像的，等于替孩子砍掉了他自己想的另一条路。
#
# v26 把 any 从「任一条」改成「多选条件」：六条全都能勾，家长定「完成几条算达成」。
#
#   v25 那版把 custom 和 stardust 挡在 any 外面，理由是「一条算不了、一条还得付钱，
#   混进来进度会说不清」。那个理由在「只算一条」的前提下成立，现在不成立了：
#   家长勾几条、要几条，是有明确答案的，算不了的那条由人判、要付钱的那条由孩子自己
#   决定付不付 —— 两件事各有各的落点，不再互相污染。
#
#   1. custom 进 any。它作为其中一条参与，但**不参与自动计数**（系统算不了它）。
#      含 custom 的心愿，ready 从一开始就是真：判定权在人手里，跟单条自定义一样。
#   2. stardust 进 any。它只有「付掉」才算做到，余额够了不算 —— 系统不替孩子付钱。
#      付不付、走这条路还是走别的路，是孩子自己的选择，所以界面在他余额够的时候
#      给他一个按钮，点不点由他。
WISH_COND_TYPES = ("fixed", "stardust", "task_count", "streak", "perfect_day",
                   "custom", "any")
# 「多选条件」里允许放进来的条件：六条全放（any 自己不套 any）
ANY_CONDS = ("fixed", "stardust", "task_count", "streak", "perfect_day", "custom")
ANY_MAX = 6
ANY_NEED_DEFAULT = 1        # 不写「完成几条」时按一条算（v25 的老数据就是这个意思）
CUSTOM_MAX = 60


def _perfect_days_in_month(member_id, day):
    """本月集满几个完美日。完美日 = 当天 7 项全满（第 01 节的定义）。"""
    n_dim = len([d for d in dimensions(day_mode(day)) if d["score"] > 0]) or 7
    first = day[:8] + "01"                     # YYYY-MM-01
    rows = db.query(
        "SELECT day, SUM(value) v, COUNT(*) n FROM score_entry"
        " WHERE member_id=? AND voided=0 AND is_fixed=1 AND day>=? AND day<=?"
        " GROUP BY day", (member_id, first, day))
    return sum(1 for r in rows if r["n"] >= n_dim and float(r["v"] or 0) >= n_dim)


def _streak_cycles(member_id, need):
    """连着几个周期固定分到了。从当前周期往前数，断了就停。

    当前周期算不算：算。他这周已经把分拿到了，没道理让他等到周六才看见进度动。
    """
    cyc = current_cycle(member_id)
    if not cyc:
        return 0
    rows = db.query(
        "SELECT * FROM cycle WHERE member_id=? AND start_date<=? ORDER BY start_date DESC",
        (member_id, cyc["start_date"]))
    n = 0
    for r in rows:
        if float(recalc_cycle(r["id"])["fixed_score"] or 0) >= need:
            n += 1
        else:
            break
    return n


def _done_task_count(member_id, since):
    """从 `since` 起，他交掉了几件发布任务（不算校准生成的修复任务）。

    锚点用**提交时刻**，不是任务建出来的时刻。差别的场景：任务昨天就发下来了，
    条件今天才定，他今天交掉 —— 这份力气是条件定下之后花的，该算。
    反过来，条件定下之前就交掉的那些一律不补记，否则门槛变成白送。

    修复任务是「必须做」，不该拿去换心愿，所以只数 kind='reward'。
    大厅任务母记录的 assignee_id 是空的，数不到，正好。
    """
    return db.query_one(
        "SELECT COUNT(*) c FROM task WHERE assignee_id=? AND kind='reward'"
        " AND status IN ('submitted','confirmed') AND COALESCE(submitted_at, created_at)>=?",
        (member_id, since or "0000"))["c"]


def _wish_cond_of(w):
    """一条心愿的条件字典。行对象和字典都要能吃。"""
    c = w["cond"] if isinstance(w, dict) and isinstance(w.get("cond"), dict) else {}
    if isinstance(w, dict) and not c:
        c = json.loads(w.get("cond_json") or "{}")
    return c


def _any_items(w):
    """多选条件里勾的那些条，滤掉形状不对的。"""
    return [it for it in (_wish_cond_of(w).get("items") or []) if isinstance(it, dict)]


def _any_need(c, n=None):
    """多选条件要完成几条算达成。

    这是 v26 新加的一格：家长勾几条、再写「做到其中几条算成」。
    n 是实际能参与计数的条数（判定和显示都用它）。
    读取侧兜底到 1 而不是报错：v25 存下来的那批 any 数据里没有 need 这个键，
    它们当时的语义就是「任一条」，读出来当 1 正好接上。
    写入侧由 _check_cond 严格卡在 1..勾选的条数，不靠这里兜。
    """
    total = len(c.get("items") or []) if n is None else n
    raw = c.get("need")
    try:
        k = int(raw) if raw is not None else ANY_NEED_DEFAULT
    except (TypeError, ValueError):
        k = ANY_NEED_DEFAULT
    if total <= 0:
        return max(1, k)
    return max(1, min(k, total))


def _selfpay_need(w):
    """这条心愿要付多少星尘。返回 None = 这条压根不用付钱。

    单选「星尘自付」读 cond.value；多选条件读里面勾的那条星尘自付。
    两处读的是同一笔钱，只是条件形状不同，所以收在一个函数里。
    """
    c = _wish_cond_of(dict(w) if not isinstance(w, dict) else w)
    if w.get("cond_type") == "stardust":
        return float(c.get("value") or 0)
    if w.get("cond_type") == "any":
        for it in (c.get("items") or []):
            if isinstance(it, dict) and it.get("type") == "stardust":
                return float(_cond_target(it) or 0)
    return None


def _auto_progress(w):
    """五种能自动算的条件。

    现算，不落库。落库就会跟真实分数不一致，而且必须有人记得在每次打分后
    回来更新它，那种「谁忘了谁就错」的设计在这套系统里已经吃过亏。
    """
    c = _wish_cond_of(w)
    ctype = w["cond_type"]
    mid = w["member_id"]
    target = c.get("value", c.get("amount", c.get("count")))

    if ctype == "fixed":
        cyc = current_cycle(mid)
        cur = float(recalc_cycle(cyc["id"])["fixed_score"] or 0) if cyc else 0.0
        target = float(target or 49)
        label, unit, where = "本周期固定分", "分", "本周期分数一到就作数，星探和任务的分不算"
    elif ctype == "stardust":
        paid = float(w.get("selfpay_stardust") or 0)
        target = float(target or 0)
        bal = float(stardust_balance(mid) or 0)
        label, unit = "自己出星尘", "星尘"
        where = "余额够了还得自己点一下付掉。掏钱这个动作本身就在训练取舍"
        pct = 100 if target <= 0 else min(100, int(round(
            (paid if paid > 0 else bal) / target * 100)))
        return {
            "known": True, "key": ctype, "label": label, "cur": paid if paid > 0 else bal,
            "balance": bal, "target": target, "unit": unit, "where": where,
            "percent": pct, "done": paid >= target > 0, "paid": paid > 0,
            "can_pay": paid <= 0 and bal >= target > 0,
            # 攒够了但还没付，进度条画满，按钮却还在 —— 这两种状态必须分开说
            "text": ("已经付掉 %g 星尘" % paid) if paid > 0
                    else "自己出 %g 星尘，现在有 %g" % (target, bal),
            "ready": paid >= target > 0,
        }
    elif ctype == "task_count":
        cur = float(_done_task_count(mid, w.get("configured_at") or w.get("created_at")))
        target = float(target or 0)
        label, unit, where = "完成的发布任务", "件", "定条件之后交的才算，之前做过的不补记"
    elif ctype == "streak":
        target = float(target or 0)
        cur = float(_streak_cycles(mid, target))
        label, unit, where = "连续达标的周期", "周", "断一周就从头数"
    elif ctype == "perfect_day":
        target = float(target or 0)
        cur = float(_perfect_days_in_month(mid, today()))
        label, unit, where = "本月的完美日", "天", "7 项全满才算一天"
    else:
        return {"known": False, "items": [], "percent": 0, "ready": False,
                "text": "条件类型「%s」不认识" % ctype}

    target = max(target, 0.0)
    # 文案在这里拼好给接口和测试用；界面自己用 num() 再排一遍，不去解析这句话。
    pct = 100 if target <= 0 else min(100, int(round(cur / target * 100)))
    hit = cur >= target
    if ctype == "stardust":
        text = "自己出 %g 星尘，现在有 %g" % (target, cur)
    else:
        text = "%s %g / %g %s" % (label, cur, target, unit)

    return {
        "known": True, "key": ctype, "label": label, "cur": cur, "target": target,
        "unit": unit, "where": where, "percent": pct, "done": bool(hit),
        "text": text, "ready": bool(hit),
    }


def _custom_progress(w, claim=None):
    """自己说好的一条。系统算不了，所以没有百分比，也没有门槛。

    判定权在人手里，但「谁说了算」分三步，一步都不能省：

    1. 孩子提交（`claim` 待审）：球在家长这边，不能再点，也不算达成；
    2. 家长确认（approved）：这一条算做到了，done 为真；
    3. 家长驳回（rejected）：不算，理由原样摆给他看，改好了可以再来一次。

    v29 之前这里只有一步 —— 孩子按下「我做到了」的那一刻心愿直接达成，
    家长那边连个待办都没有。条件是家长定的，判定却是孩子做的，那句
    「爸爸妈妈确认了就算」其实是「说了就算」。
    """
    c = _wish_cond_of(w)
    txt = str((c or {}).get("text") or "").strip()
    if claim is None and w.get("id"):
        claim = wish_claim_of(w["id"], "custom")
    claim = dict(claim) if claim else None
    st = (claim or {}).get("status") or ""
    # 上一次为什么没过。提交取的是最近一条，驳回之后再交一次就把那条理由顶掉了，
    # 而那句话正是他接着做下去的依据 —— 单独留一格带过来。
    last = None
    if w.get("id"):
        last = db.query_one("SELECT reject_note FROM wish_claim WHERE wish_id=?"
                            " AND cond_key='custom' AND status='rejected'"
                            " ORDER BY id DESC LIMIT 1", (w["id"],))
    last_note = ((dict(last) if last else {}).get("reject_note") or "")
    out = {"known": True, "key": "custom", "label": _WISH_COND_LABEL["custom"],
           "manual": True, "cur": None, "target": None, "unit": "",
           "percent": None, "text": txt,
           # 走到哪一步了：空=还没交，pending=等确认，approved=通过了，rejected=没过
           "claim_status": st, "note": (claim or {}).get("note") or "",
           "last_reject_note": last_note,
           # 谁确认的。孩子要的是「妈妈已经点头了」这一句，不是「已通过」三个字
           "by": member_name_of(claim["resolved_by"]) if (claim or {}).get("resolved_by") else ""}
    if st == "approved":
        out.update({"done": True, "ready": True, "pending": False,
                    "where": "这一条爸爸妈妈已经确认过了"})
    elif st == "pending":
        out.update({"done": False, "ready": False, "pending": True,
                    "where": "已经交给爸爸妈妈了，等他们确认，这期间不用再点"})
    elif st == "rejected":
        out.update({"done": False, "ready": True, "rejected": True,
                    "reject_note": (claim or {}).get("reject_note") or "",
                    "where": "上一次没通过，改好了可以再提交一次"})
    else:
        out.update({"done": False, "ready": True,
                    "where": "这件事系统算不了，你做到了说一声，爸爸妈妈确认了就算"})
    return out


def _any_sub_progress(w, it):
    """多选条件里的一条子条件，按它自己的类型算一次进度。"""
    t = it.get("type")
    if t == "custom":
        # 带上 id：提交记录是按心愿查的，没有 id 就查不到这一条审到哪一步了
        return _custom_progress({"cond": {"text": it.get("text")}, "id": w.get("id")})
    return _auto_progress({
        "cond_type": t, "cond": {"value": _cond_target(it)},
        "member_id": w.get("member_id"),
        # 多选里那条星尘自付跟单选那条用的是同一笔钱，都记在 selfpay_stardust 上
        "selfpay_stardust": w.get("selfpay_stardust") or 0,
        "configured_at": w.get("configured_at") or w.get("created_at"),
    })


def _any_progress(w):
    """多选条件：勾几条、做到其中 N 条就算。

    进度看的是**做到几条 / 要几条**，不是哪一条的百分比。
    v25 那版取「最接近的那条」，那是「任一条」语义下的算法；家长能定
    「完成两条算达成」之后它就不成立了 —— 做到一条的 100% 和做到两条的 0%
    会显示成同一个数，孩子照着走必然走错。

    星尘自付那一条单独说：它只有**付掉之后**才算做到，余额够了不算。
    系统不替孩子付钱，也不因为他余额够就把这条记成完成。走星尘这条路，
    还是把星尘留着、靠别的条件达成，是他自己的选择。所以他余额够的时候，
    卡片上给他一个按钮，点不点由他。
    """
    if not isinstance(w, dict):
        w = dict(w)
    c = _wish_cond_of(w)
    subs = []
    for it in _any_items(w):
        sp = _any_sub_progress(w, it)
        if not sp.get("known"):
            continue
        sp["label"] = _WISH_COND_LABEL.get(sp.get("key"), sp.get("key"))
        subs.append(sp)
    if not subs:
        return {"known": False, "items": [], "percent": None, "ready": False,
                "text": "这条心愿还没挑够条件"}
    need = _any_need(c, len(subs))
    # 自定义那条不参与自动计数：系统算不了它，能算几条算几条
    done_count = sum(1 for s in subs if s.get("done"))
    manual = any(s.get("manual") for s in subs)
    # 这条「自己写一条」现在是不是正等家长点头
    pending = any(s.get("pending") for s in subs)
    manual_ready = any(s.get("manual") and not s.get("pending") for s in subs)
    done = done_count >= need
    payable = next((s for s in subs
                    if s.get("key") == "stardust" and s.get("can_pay")), None)
    can_pay = ({"target": payable.get("target"), "balance": payable.get("balance")}
               if payable else None)
    return {
        "known": True, "key": "any", "label": _WISH_COND_LABEL["any"],
        "need": need, "done_count": done_count, "total": len(subs),
        # 主条画的是完成条数，不是某一条的百分比
        "cur": done_count, "target": need, "unit": "条",
        "percent": min(100, int(round(done_count / need * 100))) if need else 0,
        "done": bool(done),
        # 含「自己写一条」时，判定权在人手里 —— 但**正在等确认的那条不算**：
        # 孩子已经按过了，球在家长这边，这时候再给他一个能点的「我做到了」，
        # 他会以为上次没交上去，于是一遍遍重复提交。驳回之后（rejected）
        # 才重新可点：那种情况下「再试一次」正是我们希望他做的事。
        "ready": bool(done or manual_ready),
        "has_manual": bool(manual),
        "has_pending": bool(pending),
        "can_pay": can_pay,
        "paid": float(w.get("selfpay_stardust") or 0),
        "where": "这几条不用都做到，够 %d 条就行" % need,
        "text": ("够格了：要 %d 条，已经做到 %d 条" % (need, done_count)) if done
                else ("要 %d 条，已经做到 %d 条，还差 %d 条"
                      % (need, done_count, need - done_count)),
        # 子行每条各列一行。不列的话，孩子看到「还差 2 条」也不知道是哪两条在差。
        # 星尘那条没付的时候把百分比压到 99：余额够了它算出来就是 100%，
        # 可那一行旁边没有勾，两个信号打架。压一格是在说「就差你按那一下」。
        "subs": [{"key": s["key"], "text": s["text"],
                  "percent": (min(s.get("percent") or 0, 99)
                              if s.get("key") == "stardust" and not s.get("done")
                              else s.get("percent")),
                  "done": bool(s.get("done")), "manual": bool(s.get("manual")),
                  # 提交走到哪一步了：前端靠这三个值决定那一行显示按钮还是状态
                  "claim_status": s.get("claim_status") or "",
                  "pending": bool(s.get("pending")),
                  "rejected": bool(s.get("rejected")),
                  "reject_note": s.get("reject_note") or "",
                  "last_reject_note": s.get("last_reject_note") or "",
                  "by": s.get("by") or "",
                  "where": s.get("where") or "",
                  "can_pay": bool(s.get("can_pay")), "target": s.get("target")}
                 for s in subs],
    }


def wish_progress(w):
    """一条心愿的进度。三种形态从这里分派出去。"""
    ctype = w.get("cond_type") if isinstance(w, dict) else None
    if ctype == "custom":
        return _custom_progress(w)
    if ctype == "any":
        return _any_progress(w)
    return _auto_progress(w)


def wish_view(w, with_progress=False):
    """给接口用的一条心愿。progress 只给已经生效的算 —— 挂起的没有条件可算。"""
    d = dict(w)
    d["cond"] = json.loads(w["cond_json"] or "{}")
    if with_progress and w["status"] in ("active", "achieved", "claimed"):
        d["progress"] = wish_progress(d)
    else:
        d["progress"] = None
    return d


def _wish_cap_room(member_id, status):
    if status == "wished":
        key, what = "wish.max_pending", "挂着等定条件的心愿"
    else:
        key, what = "wish.max_active", "同时进行中的心愿"
    n = db.query_one("SELECT COUNT(*) c FROM wish WHERE member_id=? AND status=?",
                     (member_id, status))["c"]
    cap = int(db.cfg(key, 2))
    if n >= cap:
        return "%s最多 %d 个，先处理掉一个" % (what, cap)
    return None


def _cond_target(cond):
    """条件里的门槛数值。取不到就是 None —— 不猜、不给默认值。

    以前这里写的是 `float(target or 49)`，于是家长把门槛填成 0 会被悄悄改成 49。
    门槛是这套系统的物理定律之一，悄悄改写它比报错恶劣得多。
    """
    if not isinstance(cond, dict):
        return None
    for k in ("value", "amount", "count"):
        if cond.get(k) is not None:
            try:
                return float(cond[k])
            except (TypeError, ValueError):
                return None
    return None


def _check_cond(cond_type, cond):
    """写入口的校验。三种形态各查各的：

      · 五种自动条件 = 一个大于 0 的门槛数值
      · custom       = 一句话，系统算不了，靠人判
      · any          = 两到六条条件（六种任挑，不重复）+ 做到其中几条算成

    一律「要么原样过、要么当场拒」，不做任何兜底替换。门槛是这套系统的
    物理定律之一，悄悄改写成默认值比报错恶劣得多。
    """
    if cond_type not in WISH_COND_TYPES:
        return "条件模板不认识"
    if cond_type == "custom":
        t = str((cond.get("text") if isinstance(cond, dict) else "") or "").strip()
        if len(t) < 2:
            return "把自己定的条件写清楚，至少两个字"
        if len(t) > CUSTOM_MAX:
            return "这句话短一点，%d 字以内" % CUSTOM_MAX
        return None
    if cond_type == "any":
        items = (cond.get("items") if isinstance(cond, dict) else None) or []
        if not isinstance(items, list) or len(items) < 2:
            return "「多选条件」至少挑两条，只有一条就用上面那几种"
        if len(items) > ANY_MAX:
            return "最多挑 %d 条" % ANY_MAX
        seen = set()
        for it in items:
            if not isinstance(it, dict) or it.get("type") not in ANY_CONDS:
                return "这里只能放上面那六种条件"
            if it["type"] in seen:
                return "同一条挑了两遍"
            seen.add(it["type"])
            if it["type"] == "custom":
                # 自定义那条自己带一段话，校验跟单条时一模一样，直接复用
                bad = _check_cond("custom", it)
                if bad:
                    return bad
                continue
            v = _cond_target(it)
            if v is None or v <= 0:
                return "每条都要写一个大于 0 的数"
        raw = cond.get("need")
        try:
            need = int(raw) if raw is not None else ANY_NEED_DEFAULT
        except (TypeError, ValueError):
            return "「做到几条算达成」要写一个整数"
        if need < 1:
            return "至少要完成 1 条"
        if need > len(items):
            return "勾了 %d 条，「做到几条算达成」不能比它多" % len(items)
        return None
    v = _cond_target(cond)
    if v is None:
        return "门槛数值要写一个数"
    if v <= 0:
        return "门槛要大于 0。「做到 0 个」不算条件"
    return None


def wish_one(member_id, title, *, by_child=False, reward_desc="", operator_id=None):
    """孩子许愿。只写「想要什么」，条件留白，状态挂起。"""
    title = (title or "").strip()
    if not title:
        return {"ok": False, "msg": "先写清楚想要什么"}
    if len(title) > 40:
        return {"ok": False, "msg": "标题短一点，写不下"}
    why = _wish_cap_room(member_id, "wished")
    if why:
        return {"ok": False, "msg": why}
    # 条件故意不写：模型里 cond_type 是 NOT NULL，用空串占位。
    # 家长定条件时会覆盖它，界面上挂起的那条不显示条件，所以空串不会漏到外面。
    wid = db.execute(
        "INSERT INTO wish (member_id, title, cond_type, cond_json, reward_desc,"
        " selfpay_stardust, status, created_at, operator_id)"
        " VALUES (?,?,'','{}',?,0,'wished',?,?)",
        (member_id, title, reward_desc, now(), operator_id))
    return {"ok": True, "wish_id": wid, "status": "wished"}


def create_wish(member_id, title, cond_type="fixed", cond=None, reward_desc="", price_note="",
                selfpay=0, operator_id=None, icon=""):
    """家长直接定一个带条件的心愿，一步到位生效。

    和 wish_one 的区别只在起点：这条从 active 开始，因为条件是当场给的。
    """
    if cond_type not in WISH_COND_TYPES:
        return {"ok": False, "msg": "条件模板不认识"}
    bad = _check_cond(cond_type, cond)
    if bad:
        return {"ok": False, "msg": bad}
    why = _wish_cap_room(member_id, "active")
    if why:
        return {"ok": False, "msg": why}
    if float(selfpay) > 0:
        if stardust_balance(member_id) < float(selfpay):
            return {"ok": False, "msg": "星尘不够自付这一笔"}
        add_ledger(member_id, "pool_deposit", stardust=-float(selfpay),
                   note="心愿自付：" + title, operator_id=operator_id)
    return {"ok": True, "wish_id": db.execute(
        "INSERT INTO wish (member_id, title, cond_type, cond_json, reward_desc, price_note,"
        " selfpay_stardust, status, created_at, configured_at, configured_by, icon, operator_id)"
        " VALUES (?,?,?,?,?,?,?,'active',?,?,?,?,?)",
        (member_id, title, cond_type, json.dumps(cond or {}, ensure_ascii=False), reward_desc,
         price_note, float(selfpay), now(), now(), operator_id,
         clean_icon(icon), operator_id))}


def pay_wish_selfpay(wish_id, operator_id=None):
    """把「星尘自付」那一步的星尘付掉。

    单选「星尘自付」和多选条件里勾的那条星尘自付走同一个入口：两条路掏的是
    同一笔钱，区别只在条件长什么样。多选里付掉之后，那一条才算「做到」，
    别的条照旧各算各的 —— 孩子也可以不付，靠别的条凑够条数。

    为什么不让系统在条件达标时自己扣：不打招呼就扣钱，跟被偷没区别，
    孩子下一次会把星尘先花掉躲开。为什么要单独一步：掏钱这个动作本身
    就是这条条件存在的理由，系统替他掏，这笔钱就退化成一次自动转账。
    """
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wish_id,))
    if not w:
        return {"ok": False, "msg": "心愿不存在"}
    if w["status"] != "active":
        return {"ok": False, "msg": "这条心愿现在不是进行中"}
    need = _selfpay_need(dict(w))
    if need is None:
        return {"ok": False, "msg": "这条心愿不用付星尘"}
    if need <= 0:
        return {"ok": False, "msg": "这条星尘门槛没写数"}
    if float(w["selfpay_stardust"] or 0) > 0:
        return {"ok": False, "msg": "这笔已经付过了"}
    bal = float(stardust_balance(w["member_id"]) or 0)
    if bal < need:
        return {"ok": False, "msg": "还差 %g 星尘" % (need - bal)}
    add_ledger(w["member_id"], "pool_deposit", stardust=-need,
               note="心愿自付：" + w["title"], operator_id=operator_id)
    db.execute("UPDATE wish SET selfpay_stardust=? WHERE id=?", (need, wish_id))
    return {"ok": True, "paid": need, "balance": stardust_balance(w["member_id"])}


def configure_wish(wish_id, cond_type, cond=None, *, reward_desc=None, price_note=None,
                   operator_id=None, icon=None):
    """家长给一条挂起的心愿定条件 —— 这一步就是「点亮」。

    名额护栏放在这里而不是许愿那一刻：孩子许愿不占「进行中」的名额，
    变成进行中才占。跟 v15 把额度检查挪到领取时刻是同一条道理，
    在事情真正发生的那一步查，才不会出现「先占了名额又没生效」。

    图标也在这步定。孩子许愿那一刻不给他选图：心愿是他自己许的，但配什么图
    由家长点亮时顺手挑一张。孩子的许愿界面压根没有选图这个入口。
    """
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wish_id,))
    if not w:
        return {"ok": False, "msg": "心愿不存在"}
    if w["status"] != "wished":
        return {"ok": False, "msg": "这条心愿不是待定状态，改不了它的条件"}
    bad = _check_cond(cond_type, cond)
    if bad:
        return {"ok": False, "msg": bad}
    why = _wish_cap_room(w["member_id"], "active")
    if why:
        return {"ok": False, "msg": why}
    db.execute(
        "UPDATE wish SET cond_type=?, cond_json=?, reward_desc=?, price_note=?,"
        " status='active', configured_at=?, configured_by=?, ready_notified_at='',"
        " icon=COALESCE(?, icon) WHERE id=?",
        (cond_type, json.dumps(cond or {}, ensure_ascii=False),
         w["reward_desc"] if reward_desc is None else reward_desc,
         w["price_note"] if price_note is None else price_note,
         now(), operator_id,
         # 没传就保持原样（COALESCE），传了才写。传空串是「把图去掉」。
         None if icon is None else clean_icon(icon), wish_id))
    push_notify(w["member_id"], "wish_active", "你的愿望点亮了",
                "「%s」的条件是：%s" % (w["title"], wish_cond_text({
                    "cond_type": cond_type,
                    "cond_json": json.dumps(cond or {}, ensure_ascii=False)})))
    return {"ok": True, "status": "active"}


def update_wish_status(wish_id, status, operator_id=None):
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wish_id,))
    if not w:
        return {"ok": False, "msg": "心愿不存在"}
    if status == "cancelled" and w["selfpay_stardust"]:
        add_ledger(w["member_id"], "pool_deposit", stardust=w["selfpay_stardust"],
                   note="心愿撤回，星尘全额退回", operator_id=operator_id)
    col = {"achieved": "achieved_at", "claimed": "claimed_at", "cancelled": "cancelled_at"}[status]
    if status == "cancelled":
        # v18：结束的心愿要进历史，历史里得看得出这是「被驳回」还是「自己放弃」。
        # 只存一个 cancelled 的话，这两件事在界面上长得一模一样，
        # 而它们对孩子完全是两句话：一个是「你不同意」，一个是「我自己不要了」。
        db.execute("UPDATE wish SET status=?, %s=?, closed_by=?, closed_from=? WHERE id=?" % col,
                   (status, now(), operator_id, w["status"], wish_id))
        # 别人替你结束的才通知。自己撤回的自己知道，再推一条等于复读。
        if w["status"] == "wished" and operator_id and operator_id != w["member_id"]:
            push_notify(w["member_id"], "wish_rejected", "这个愿望没被答应",
                        "「%s」被驳回了，去问问为什么。" % w["title"])
        return {"ok": True}
    db.execute("UPDATE wish SET status=?, %s=? WHERE id=?" % col, (status, now(), wish_id))
    if status == "achieved":
        push_notify(w["member_id"], "wish_achieved", "愿望达成了",
                    "「%s」%s" % (w["title"], w["reward_desc"] or ""))
    elif status == "claimed":
        push_notify(w["member_id"], "wish_claimed", "愿望兑现了",
                    "「%s」已经给你了" % w["title"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# 心愿：按哪一条提交（v29）
# ---------------------------------------------------------------------------
def wish_claim_of(wish_id, key="custom"):
    """这条心愿在这一条条件下**最近**的一次提交。

    取最近而不是取待审：驳回之后孩子还能再提交一次，取「待审的那条」
    会把上一次为什么没通过藏起来，而那句话正是他接着做下去的依据。
    """
    return db.query_one("SELECT * FROM wish_claim WHERE wish_id=? AND cond_key=?"
                        " ORDER BY id DESC LIMIT 1", (wish_id, key))


def _wish_cond_keys(w):
    """这条心愿里挂着哪几种条件。提交的时候按这个名对号入座。"""
    t = w.get("cond_type")
    if t == "custom":
        return {"custom"}
    if t == "any":
        return {it.get("type") for it in _any_items(w) if isinstance(it, dict)}
    return {t} if t else set()


def submit_wish_cond(wish_id, key, note="", operator_id=None):
    """孩子就某一条条件说「我做到了」。

    只有系统算不了的那条（家长自己写的一句话）走这条路。分数、星尘、
    任务数、连着几周这些，系统自己算得出来 —— 算够了就是够了，
    再让他为了一件已经成立的事实去等人批，那是把判定权从系统手里
    收回来交给大人，孩子等的那几天里条件一直在变。
    """
    w = db.query_one("SELECT * FROM wish WHERE id=?", (wish_id,))
    w = dict(w) if w else None
    if not w:
        return {"ok": False, "msg": "心愿不存在"}
    if w["status"] != "active":
        return {"ok": False, "msg": "这条心愿现在不在进行中"}
    if not operator_id or int(operator_id) != int(w["member_id"]):
        # 家长不能替孩子说「我做到了」：那是他自己的事，替他说就等于替他完成
        return {"ok": False, "msg": "这句话只能他自己说"}
    key = str(key or "").strip()
    if key not in _wish_cond_keys(w):
        return {"ok": False, "msg": "这条心愿里没有这一条条件"}
    if key != "custom":
        return {"ok": False, "msg": "这一条系统自己算得出来，够了会自动算上，不用提交"}
    old = wish_claim_of(wish_id, key)
    if old and old["status"] == "pending":
        return {"ok": False, "msg": "上一次提交还在等爸爸妈妈确认"}
    cid = db.execute(
        "INSERT INTO wish_claim (wish_id, cond_key, note, status, created_at, created_by)"
        " VALUES (?,?,?,'pending',?,?)",
        (wish_id, key, str(note or "").strip()[:200], now(), operator_id))
    push_notify(None, "wish_claim", "孩子说做到了",
                "「%s」有 %s 提交了一条，等你们确认"
                % (w["title"], member_name_of(w["member_id"])))
    return {"ok": True, "claim_id": cid, "status": "pending"}


def resolve_wish_claim(claim_id, approve, operator_id=None, reject_note=""):
    """家长确认孩子提交的那一条。通过就算这一条做到了。"""
    c = db.query_one("SELECT * FROM wish_claim WHERE id=?", (claim_id,))
    if not c:
        return {"ok": False, "msg": "没有这条提交"}
    if not is_judge(operator_id):
        return {"ok": False, "msg": "要爸爸妈妈来确认"}
    if c["status"] != "pending":
        return {"ok": False, "msg": "这条已经处理过了"}
    w = db.query_one("SELECT * FROM wish WHERE id=?", (c["wish_id"],))
    if not w:
        return {"ok": False, "msg": "心愿不存在"}
    if not approve:
        why = str(reject_note or "").strip()
        if not why:
            # 驳回理由对孩子可见，写不出理由的驳回等于「我说不行就不行」
            return {"ok": False, "msg": "不通过要写一句为什么，这句话孩子看得见"}
        db.execute("UPDATE wish_claim SET status='rejected', reject_note=?,"
                   " resolved_at=?, resolved_by=? WHERE id=?",
                   (why, now(), operator_id, claim_id))
        push_notify(w["member_id"], "wish_rejected", "这一条还没算",
                    "「%s」：%s" % (w["title"], why))
        return {"ok": True, "status": "rejected"}
    db.execute("UPDATE wish_claim SET status='approved', resolved_at=?, resolved_by=?"
               " WHERE id=?", (now(), operator_id, claim_id))
    # 通过后整条心愿够不够格是现算的：够了他会收到「心愿达成了」，
    # 不够说明还差别的条件，那就只是这一条记上了，心愿继续走。
    p = wish_progress(dict(w))
    if p.get("done"):
        update_wish_status(w["id"], "achieved", operator_id=operator_id)
    else:
        push_notify(w["member_id"], "wish_claim_ok", "这一条算做到了",
                    "「%s」：你提交的这条通过了，还差别的条件。" % w["title"])
    return {"ok": True, "status": "approved", "done": bool(p.get("done"))}


def pending_wish_claims(member_id=None):
    """等着家长点头的那几条提交。审核页用。"""
    sql = ("SELECT c.*, w.title, w.member_id, w.cond_type, m.name AS who,"
           " ob.name AS by_name FROM wish_claim c"
           " JOIN wish w ON w.id=c.wish_id"
           " JOIN member m ON m.id=w.member_id"
           " LEFT JOIN member ob ON ob.id=c.created_by"
           " WHERE c.status='pending'")
    args = []
    if member_id:
        sql += " AND c.wish_id IN (SELECT id FROM wish WHERE member_id=?)"
        args.append(member_id)
    sql += " ORDER BY c.id"
    rows = []
    for r in db.query(sql, args):
        w = dict(db.query_one("SELECT * FROM wish WHERE id=?", (r["wish_id"],)) or {})
        it = _cond_item_text(w, r["cond_key"]) if w else ""
        rows.append({"id": r["id"], "wish_id": r["wish_id"], "title": r["title"],
                     "who": r["who"], "member_id": r["member_id"],
                     "cond_key": r["cond_key"], "cond_text": it,
                     "note": r["note"], "created_at": r["created_at"],
                     "cond_type": r["cond_type"]})
    return rows


def _cond_item_text(w, key):
    """这一条条件的原话。孩子提交的是哪一条，家长要看的是这一句，不是类型名。"""
    t = w.get("cond_type")
    if t == "custom":
        return str((_wish_cond_of(w) or {}).get("text") or "").strip()
    for it in _any_items(w):
        if isinstance(it, dict) and it.get("type") == key:
            if key == "custom":
                return str(it.get("text") or "").strip()
            return (_WISH_COND_LABEL.get(key, key) + " " + str(_cond_target(it))).strip()
    return _WISH_COND_LABEL.get(key, key)


def check_wish_ready(member_id):
    """心愿进度刚够的那一刻，给孩子推一条。

    进度是现算的（wish_progress 刻意不落库），所以「刚刚够」这件事没有
    现成的信号，得有人主动来问一次。调用点放在分数会变的地方：
    打分、任务确认、周期结算。

    防重报靠 ready_notified_at，它存的不是时刻而是**当前周期的起点日**：
    「本周期已经报过了」。存时刻的话，下周同一件心愿进度又够了，
    系统看时间戳非空就不再出声，孩子会以为系统忘了。
    条件被重新设定时这一列清空，重新数。
    """
    if not is_player(member_id):
        return []
    wk = week_start_of(today())
    hit = []
    for w in db.query("SELECT * FROM wish WHERE member_id=? AND status='active'"
                      " AND (ready_notified_at IS NULL OR ready_notified_at!=?)",
                      (member_id, wk)):
        if not wish_progress(dict(w)).get("done"):
            continue
        push_notify(member_id, "wish_ready", "心愿的进度够了",
                    "「%s」的条件已经达成，等爸爸妈妈确认。" % w["title"])
        db.execute("UPDATE wish SET ready_notified_at=? WHERE id=?", (wk, w["id"]))
        hit.append(w["id"])
    return hit


# ---------------------------------------------------------------------------
# 许愿池
# ---------------------------------------------------------------------------
def active_pool():
    return db.query_one("SELECT * FROM wish_pool WHERE status='active' ORDER BY id LIMIT 1")


def pool_templates():
    """许愿池能设成什么。

    只给体验型模板，不给自由填。归某一个人的东西走心愿单 —— 不然被罚的
    那个人的钱，就变成了别人的礼物，这在兄弟姐妹之间是相当锋利的怨气来源。
    清单在 seed_data.POOL_TEMPLATES，改模板改那一处。
    """
    return [{"title": t, "target_desc": d} for t, d in seed_data.POOL_TEMPLATES]


def create_pool(title, target_desc="", target_stardust=0, operator_id=None):
    """许愿池目标只限全家共享的体验型。归某一个人的东西走心愿单。

    标题必须来自模板：设置页只让挑，不让写。理由和 pool_templates 一样，
    「只能选体验型」这句话如果只写在界面上，接口就成了一道敞开的门 ——
    谁绕过界面传一个「给弟弟买个玩具」进来，池子照样会建出来。
    """
    title = (title or "").strip()
    allowed = {t for t, _d in seed_data.POOL_TEMPLATES}
    if title not in allowed:
        return {"ok": False, "msg": "许愿池只放全家一起的体验型目标，从模板里挑一个"}
    target_stardust = float(target_stardust or 0)
    if target_stardust <= 0:
        return {"ok": False, "msg": "要攒多少星尘得填一个正数"}
    return {"ok": True, "pool_id": db.execute(
        "INSERT INTO wish_pool (title, target_desc, target_stardust, status, created_at)"
        " VALUES (?,?,?,'active',?)", (title, target_desc, target_stardust, now()))}


def pool_progress(pool_id=None):
    p = db.query_one("SELECT * FROM wish_pool WHERE id=?", (pool_id,)) if pool_id else active_pool()
    if not p:
        return None
    s = db.query_one("SELECT COALESCE(SUM(stardust),0) s, COALESCE(SUM(cash),0) c"
                     " FROM wish_pool_entry WHERE pool_id=?", (p["id"],))
    d = dict(p)
    d["collected_stardust"] = s["s"]
    d["collected_cash"] = s["c"]
    d["percent"] = round(s["s"] / p["target_stardust"] * 100, 1) if p["target_stardust"] else 0
    return d


def deposit_pool(member_id, stardust, pool_id=None, operator_id=None):
    p = db.query_one("SELECT * FROM wish_pool WHERE id=?", (pool_id,)) if pool_id else active_pool()
    if not p:
        return {"ok": False, "msg": "还没有许愿池目标，先在家长侧设一个"}
    # 负数投币等于凭空造星尘：stardust_balance < -100 恒为假，-(-100) 又是一笔进账。
    # 数量必须在引擎这一层判，接口层漏了也不能漏这里。
    stardust = float(stardust or 0)
    if stardust <= 0:
        return {"ok": False, "msg": "投币数量不对"}
    if stardust_balance(member_id) < stardust:
        return {"ok": False, "msg": "星尘不够"}
    add_ledger(member_id, "pool_deposit", stardust=-stardust, note="投许愿池：%s" % p["title"],
               operator_id=operator_id)
    db.execute("INSERT INTO wish_pool_entry (pool_id, member_id, source, stardust, note, ts)"
               " VALUES (?,?,'selfpay',?,?,?)", (p["id"], member_id, stardust, "主动投币", now()))
    return {"ok": True, "pool": pool_progress(p["id"])}


# ---------------------------------------------------------------------------
# 家长忘打卡兜底（v30）
#
# 规则：当晚提醒家长打分，次日 12:00 前可补打；过了 12:00 那天还是空白，
# 系统自己按满分记 —— 家长自己的疏忽，不该让孩子少一天分。
#
# 三条取舍：
#   1. 判定的时点是「次日 12:00」，不是「过了多久」。这跟家长手动补打
#      （score.backfill_days）是两条路：那条留给想改分的人，这条保证孩子
#      不吃亏，互不干扰。
#   2. 入口只有一个 —— notify 的定时线程每 5 分钟问一次。刻意不挂在
#      「打开页面」上：这是账，不是提醒，不能取决于谁哪天心血来潮点开。
#   3. 罚的是「全家」不是某个孩子，一天只罚一笔。三个孩子都漏打也是
#      100 星尘一次 —— 那是同一次疏忽。
#
# v34 补上边界。原来「这天有没有固定分记录」是唯一的判据，于是系统一上线
# 就往回看 7 天，把这套系统还不存在的那些天全判成「忘了打分」：19 号晚上
# 装好，18 号就挨一笔罚款。缺的不是代码，是规则本身没有起点。现在起点有
# 两条，都在下面这两个函数里：
#   start_date()  —— 全家的起用日，默认建库那天，设置页可改（family.start_date）
#   member.created_at —— 每个孩子自己的开号日，新开的账号不背之前的账
# ---------------------------------------------------------------------------
MISSED_PENALTY_STARDUST = 100     # 全家忘打卡一次注入许愿池的星尘
MISSED_LOOKBACK_DAYS = 7          # 回看天数的兜底默认值，正式值在设置页
MISSED_NOTE = "系统补记：当天没人打分"


def _is_day(s):
    """是不是一个规规矩矩的 YYYY-MM-DD。填坏了要能认出来。"""
    t = str(s or "")
    if len(t) < 10:
        return False
    try:
        return fmt(parse_day(t)) == t[:10]
    except Exception:
        return False


def start_date():
    """这个家开始用这套系统的日子。判「忘打卡」的下边界（v34）。

    起用日当天与之前的日子：不补分、不罚星尘、不留日志。那几天这套系统还
    不存在，谈不上「忘了打分」；起用日当天也不算 —— 那天常常是傍晚才装好，
    只留一两个小时给家长打分不合理。

    默认取建库那天（建库时写进 family.start_date），家长可在设置页改。
    读不出来或者填坏了，退回成员表里最早那条记录的时间：宁可少判几天，
    也不拿一个错的边界去罚款。
    """
    raw = str(db.cfg("family.start_date", "") or "").strip()
    if _is_day(raw):
        return raw[:10]
    row = db.query_one("SELECT MIN(created_at) v FROM member")
    d = str((row["v"] if row else "") or "")[:10]
    return d if _is_day(d) else ""


def _missed_deadline(day):
    """这一天该打完分的最后时点 = 次日 12:00。"""
    return datetime.combine(parse_day(day) + timedelta(days=1), time(12, 0))


def missed_kids(day):
    """这一天还空着、该由系统补满分的孩子。

    「空着」= 一条固定分记录都没有。只打了星探、或者只改过别的东西都不算，
    因为「没打分」在孩子那边就是少了一天分，跟一条记录都没有是一回事。

    v34：账号开出来那天与之前不判。新加一个孩子进来，不能让他背着他还不
    存在的那几天的账 —— 那跟他忘没忘一点关系都没有。
    """
    out = []
    for k in _kids():
        open_day = str(k["created_at"] or "")[:10]
        if _is_day(open_day) and day <= open_day:
            continue
        n = db.query_one(
            "SELECT COUNT(*) c FROM score_entry WHERE member_id=? AND day=?"
            " AND is_fixed=1 AND voided=0", (k["id"], day))["c"]
        if n:
            continue
        cyc = get_or_create_cycle(k["id"], day)
        if cyc and cyc["status"] == "settled":
            continue                  # 结过账的那一周不再回头改
        out.append(k)
    return out


def _fill_missed_day(kid, day):
    """给一个孩子补一天的满分。

    不走 submit_day：那条路要操作人、要过补打窗口、还要判修正窗口。
    这里一没有操作人（是系统在补），二本来就发生在补打窗口以外。

    补记完这一天就锁死了：submit_day 遇到带 MISSED_NOTE 的记录会直接拒绝，
    分数只有家长调整那条路能改。原来这里是「家长当天仍能在 24 小时修正
    窗口内改掉」，那等于「超时」只在界面上成立，改一处分罚款已经发生却
    还留着一个改分按钮。
    """
    mid = kid["id"]
    cycle = get_or_create_cycle(mid, day)
    mode = day_mode(day)
    dims = dimensions(mode)
    for d in dims:
        db.execute(
            "INSERT INTO score_entry (member_id, cycle_id, day, dimension_id, value, is_fixed,"
            " mode, note, operator_id, created_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
            (mid, cycle["id"], day, d["id"], float(d["score"]), mode, MISSED_NOTE, None, now()))
    full = round(sum(float(d["score"]) for d in dims), 2)
    recalc_cycle(cycle["id"])
    add_ledger(mid, "daily_score", cycle_id=cycle["id"], day=day, energy=full,
               note="%s 是空的，系统按满分补记 %g 分" % (day, full), operator_id=None,
               meta={"auto": True, "reason": "missed_score"})
    check_wish_ready(mid)


def _missed_pool_penalty(day, kids):
    """全家忘打卡的罚款入池。一天一笔，几个孩子都漏也是这一笔。

    判据放在 wish_pool_log 而不是 wish_pool_entry 上：那张表按「哪一天」
    归属，正好是这里的口径，而且它还记着「漏的是哪几个孩子」，
    这是罚款本身说不清的事。
    """
    if db.query_one("SELECT id FROM wish_pool_log WHERE kind='penalty' AND day=?", (day,)):
        return None
    names = [k["name"] for k in kids]
    kids_json = json.dumps([{"id": k["id"], "name": k["name"]} for k in kids],
                           ensure_ascii=False)
    pool = active_pool()
    amount = float(MISSED_PENALTY_STARDUST)

    if not pool:
        # 还没设过目标。罚款无处可投，但这件事得留下 —— 日志的作用是让
        # 家长看见「那天我们两个都忘了」，不是记一笔债。等以后设了目标
        # 也不补发，孩子没有因为这 100 星尘损失什么。
        db.execute(
            "INSERT INTO wish_pool_log (pool_id, kind, day, member_id, kids_json, kids_days,"
            " stardust, counted, note, ts)"
            " VALUES (NULL,'penalty',?,NULL,?,?,0,0,?,?)",
            (day, kids_json, len(kids),
             "全家忘打卡。当天还没有许愿池目标，%g 星尘罚款没处投" % amount, now()))
        push_notify(None, "missed_score", "补记 %s：那天没人打分" % day,
                    "%s 这天空着，系统按满分补上了（往回补的历史空白，不是今天的账）。"
                    "罚款没入池（还没设许愿池目标）。" % "、".join(names))
        return None

    db.execute("INSERT INTO wish_pool_entry (pool_id, member_id, source, stardust, note, ts)"
               " VALUES (?,NULL,'penalty',?,?,?)",
               (pool["id"], amount, "全家忘打卡罚款入池：%s" % day, now()))
    db.execute(
        "INSERT INTO wish_pool_log (pool_id, kind, day, member_id, kids_json, kids_days,"
        " stardust, counted, note, ts) VALUES (?,?,?,NULL,?,?,?,1,?,?)",
        (pool["id"], "penalty", day, kids_json, len(kids), amount,
         "全家忘打卡，罚 %g 星尘投入「%s」" % (amount, pool["title"]), now()))
    push_notify(None, "missed_score", "补记 %s：那天没人打分" % day,
                "%s 这天空着，系统按满分补上了（往回补的历史空白，不是今天的账），"
                "罚 %g 星尘投进许愿池。" % ("、".join(names), amount))
    return amount


def ensure_missed_scores(day=None, lookback_days=None):
    """把「过了次日 12:00 还是空白」的日子补成满分，并把罚款投进许愿池。

    幂等：补分看 score_entry 里有没有固定分，罚款看 wish_pool_log 里
    当天记过没有。跑一次、跑十次，结果一样。返回值只用于测试与排错。

    范围由两道边界夹住（v34）：下界是起用日（含当天不判），上界是
    「回看窗口」与「次日 12:00」。两头都定死，才不会出现「系统把安装之前
    的那几天记成漏打」这种事。
    """
    d0 = parse_day(day or today())
    back = int(lookback_days if lookback_days is not None
               else db.cfg("missed.lookback_days", MISSED_LOOKBACK_DAYS))
    start = start_date()
    out = {"filled": [], "penalty": [], "before_start": 0}
    for i in range(max(0, back), 0, -1):
        dd = fmt(d0 - timedelta(days=i))
        if start and dd <= start:
            out["before_start"] += 1
            continue                  # 起用日当天与之前：这套系统还不存在
        if _dtnow() < _missed_deadline(dd):
            continue                  # 还没到「次日 12:00」
        if is_transition(dd):
            continue                  # 过渡日不计分，没有「漏打」这回事
        kids = missed_kids(dd)
        if not kids:
            continue
        for k in kids:
            _fill_missed_day(k, dd)
            out["filled"].append({"day": dd, "member_id": k["id"], "name": k["name"]})
        amt = _missed_pool_penalty(dd, kids)
        if amt:
            out["penalty"].append({"day": dd, "stardust": amt, "kids": len(kids)})
    return out


# ---------------------------------------------------------------------------
# 加时申请 / 求助
# ---------------------------------------------------------------------------
def request_overtime(member_id, day=None, minutes=30, reason=""):
    """加时申请：10 星尘换 30 分钟，每周最多 2 次（第 09 章）。

    时长不给外部传：定价是按「一条 30 分钟」定的，让它能传任意分钟就等于
    10 星尘可以买两小时。要改时长改设置，别改调用方。
    """
    day = day or today()
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    if (day or "") > today():
        # 拿下周的日期来申请，会让本周的配额凭空清零
        return {"ok": False, "msg": "只能申请今天的"}
    minutes = float(db.cfg("overtime.minutes", 30))
    cap = int(db.cfg("overtime.weekly_cap", 2))
    wk = week_start_of(day)
    used = db.query_one("SELECT COUNT(*) c FROM overtime_request WHERE member_id=? AND week_key=?"
                        " AND status!='rejected'", (member_id, wk))["c"]
    if used >= cap:
        return {"ok": False, "msg": "本周加时申请已经用满 %d 次" % cap}
    cost = float(db.cfg("overtime.cost", 10))
    if stardust_balance(member_id) < cost:
        return {"ok": False, "msg": "星尘不够（需要 %g）" % cost}
    rid = db.execute(
        "INSERT INTO overtime_request (member_id, day, week_key, minutes, cost, status, reason, ts)"
        " VALUES (?,?,?,?,?,'pending',?,?)",
        (member_id, day, wk, minutes, cost, reason, now()))
    push_notify(None, "overtime", "有加时申请要处理", "同意或拒绝（拒绝要写理由）")
    return {"ok": True, "request_id": rid, "cost": cost, "minutes": minutes,
            "note": "只突破当日单次与晚间上限，不突破学习前置"}


def resolve_overtime(request_id, approve, operator_id=None, reject_note=""):
    r = db.query_one("SELECT * FROM overtime_request WHERE id=?", (request_id,))
    if not r:
        return {"ok": False, "msg": "申请不存在"}
    if r["status"] != "pending":
        return {"ok": False, "msg": "这条申请已经处理过了"}
    if not approve and not (reject_note or "").strip():
        return {"ok": False, "msg": "拒绝必须写理由，而且孩子能看到"}
    if approve:
        add_ledger(r["member_id"], "overtime", day=r["day"], stardust=-r["cost"],
                   minutes=r["minutes"], note="加时申请通过：+%g 分钟" % r["minutes"],
                   operator_id=operator_id)
    db.execute("UPDATE overtime_request SET status=?, reject_note=?, operator_id=?, resolved_at=?"
               " WHERE id=?", ("approved" if approve else "rejected", reject_note,
                               operator_id, now(), request_id))
    # 结果要让孩子看到：被拒的理由也一起发过去。
    # 只在孩子翻记录时才发现被拒了、而且不知道为什么，是家庭摩擦最大的来源。
    push_notify(r["member_id"], "overtime",
                "加时通过了" if approve else "加时没通过",
                ("+%g 分钟，%s 之前用完" % (r["minutes"], curfew_text(r["day"]))) if approve
                else reject_note)
    return {"ok": True, "approved": bool(approve)}


def request_help(member_id, detail, day=None, operator_id=None):
    """常驻的求助按钮：主动说「这题我不会」，家长核实后 +1 星尘（第 10 章）。

    上限只数**已核实**的次数 —— 被拒的和还在等的都不该占额度，
    不然家长拖着不处理就把孩子这周的求助额度锁死了。
    但待核实的最多压一条：一次堆五条「我不会」，家长那一侧就变成了批量点击。
    """
    day = day or today()
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    detail = (detail or "").strip()
    if not detail:
        return {"ok": False, "msg": "写一句卡在哪儿，是哪一题、哪一步"}
    if len(detail) > 200:
        return {"ok": False, "msg": "写短一点，200 字以内"}
    wk = week_start_of(day)
    done = db.query_one("SELECT COUNT(*) c FROM help_request WHERE member_id=? AND week_key=?"
                        " AND verified_at IS NOT NULL AND stardust>0", (member_id, wk))["c"]
    cap = int(db.cfg("help.weekly_cap", 3))
    if done >= cap:
        return {"ok": False, "msg": "本周求助已经记满 %d 次，这条留着下次问" % cap}
    waiting = db.query_one("SELECT COUNT(*) c FROM help_request WHERE member_id=? AND week_key=?"
                           " AND verified_at IS NULL", (member_id, wk))["c"]
    if waiting:
        return {"ok": False, "msg": "上一条还没核实，等家长看完再记新的"}
    rid = db.execute(
        "INSERT INTO help_request (member_id, day, week_key, detail, ts) VALUES (?,?,?,?,?)",
        (member_id, day, wk, detail, now()))
    push_notify(None, "help", "孩子按了求助", detail)
    return {"ok": True, "request_id": rid, "left": cap - done, "note": "家长核实后发放"}


def verify_help(request_id, operator_id=None, approved=True):
    r = db.query_one("SELECT * FROM help_request WHERE id=?", (request_id,))
    if not r:
        return {"ok": False, "msg": "记录不存在"}
    if r["verified_at"]:
        return {"ok": False, "msg": "已经核实过了"}
    if not approved:
        db.execute("UPDATE help_request SET verified_by=?, verified_at=?, stardust=0 WHERE id=?",
                   (operator_id, now(), request_id))
        return {"ok": True, "stardust": 0}
    amt = float(db.cfg("help.stardust", 1))
    add_ledger(r["member_id"], "help", day=r["day"], stardust=amt,
               note="求助（说清楚卡在哪里）：" + r["detail"], operator_id=operator_id)
    db.execute("UPDATE help_request SET verified_by=?, verified_at=?, stardust=? WHERE id=?",
               (operator_id, now(), amt, request_id))
    return {"ok": True, "stardust": amt}


# ---------------------------------------------------------------------------
# 有效期：续期 / 到期折半返还 / 假期顺延
# ---------------------------------------------------------------------------
def expiring_soon(member_id, days=None):
    days = days or int(db.cfg("notify.card_expire_days", 14))
    limit = fmt(parse_day(today()) + timedelta(days=days))
    return db.query(
        "SELECT h.*, i.name, i.rarity, i.price, i.shelf_life_days, i.renew_cost_pct, i.renew_times,"
        " i.expire_refund FROM holding h JOIN item i ON i.id=h.item_id"
        " WHERE h.member_id=? AND h.qty>0 AND h.expires_at IS NOT NULL AND h.expires_at<=?"
        " ORDER BY h.expires_at", (member_id, limit))


def renew_card(holding_id, operator_id=None, owner_id=None):
    h = db.query_one("SELECT h.*, i.name, i.price, i.renew_cost_pct, i.renew_times,"
                     " i.shelf_life_days FROM holding h JOIN item i ON i.id=h.item_id WHERE h.id=?",
                     (holding_id,))
    if not h:
        return {"ok": False, "msg": "找不到这张卡"}
    # 扣的是卡主的星尘，所以卡必须是卡主自己的。
    # 不校验归属的话，传别人的 holding_id 就能花别人的星尘续别人的卡。
    if owner_id is not None and h["member_id"] != owner_id:
        return {"ok": False, "msg": "这张卡不是你的"}
    if h["renew_count"] >= (h["renew_times"] or 1):
        return {"ok": False, "msg": "这张卡已经续过一次了"}
    # 只能在提醒期内续（剩 N 天以内）。随时能续等于没有有效期，
    # 而且会把「什么时候用掉它」这个决策直接抹掉。
    notice = int(db.cfg("notify.card_expire_days", 14))
    if h["expires_at"]:
        left = (parse_day(h["expires_at"]) - parse_day(today())).days
        if left > notice:
            return {"ok": False, "msg": "还有 %d 天到期，进提醒期（剩 %d 天以内）才能续"
                                       % (left, notice)}
    cost = round((h["price"] or 0) * (h["renew_cost_pct"] or 20) / 100.0, 2)
    if stardust_balance(h["member_id"]) < cost:
        return {"ok": False, "msg": "续期需要 %g 星尘" % cost}
    add_ledger(h["member_id"], "renew", stardust=-cost, note="续期 %s" % h["name"],
               operator_id=operator_id)
    base = parse_day(h["expires_at"]) if h["expires_at"] else parse_day(today())
    # 续期天数是固定 90 天，不跟着卡本身的有效期走：
    # 传说卡本来 120 天，跟着走就变成续一次拿 120 天，比新卡还划算。
    add_days = int(db.cfg("card.renew_days", 90))
    new_exp = fmt(max(base, parse_day(today())) + timedelta(days=add_days))
    db.execute("UPDATE holding SET expires_at=?, renew_count=renew_count+1 WHERE id=?",
               (new_exp, holding_id))
    return {"ok": True, "cost": cost, "expires_at": new_exp, "days": add_days}


def process_expiry(member_id=None, operator_id=None):
    """到期的卡折半转星尘，不直接没收。"""
    sql = ("SELECT h.*, i.name, i.expire_refund FROM holding h JOIN item i ON i.id=h.item_id"
           " WHERE h.qty>0 AND h.expires_at IS NOT NULL AND h.expires_at<?")
    args = [today()]
    if member_id:
        sql += " AND h.member_id=?"
        args.append(member_id)
    out = []
    for h in db.query(sql, args):
        refund = round((h["expire_refund"] or 0) * h["qty"], 2)
        db.execute("UPDATE holding SET qty=0 WHERE id=?", (h["id"],))
        lid = add_ledger(h["member_id"], "expire_refund", stardust=refund,
                         note="%s 到期，折半转 %g 星尘" % (h["name"], refund),
                         operator_id=operator_id)
        add_ledger_item(lid, h["member_id"], h["item_id"], -h["qty"], "到期")
        out.append({"item": h["name"], "qty": h["qty"], "refund": refund})
    return out


def apply_holiday_delay(member_id=None, operator_id=None):
    """假期保护窗：到期日落在假期内或假期前 N 天，顺延到假期结束后 M 天。"""
    before = int(db.cfg("holiday.delay_window_before", 14))
    after = int(db.cfg("holiday.delay_window_after", 7))
    max_per_year = int(db.cfg("holiday.delay_max_per_year", 2))
    out = []
    for hd in db.query("SELECT * FROM holiday WHERE end_date>=?", (today(),)):
        win_start = fmt(parse_day(hd["start_date"]) - timedelta(days=before))
        target = fmt(parse_day(hd["end_date"]) + timedelta(days=after))
        sql = ("SELECT h.*, i.name FROM holding h JOIN item i ON i.id=h.item_id"
               " WHERE h.qty>0 AND h.expires_at IS NOT NULL AND h.expires_at<=?"
               " AND h.expires_at>=? AND h.delay_count<?")
        args = [hd["end_date"], win_start, max_per_year]
        if member_id:
            sql += " AND h.member_id=?"
            args.append(member_id)
        for h in db.query(sql, args):
            # 「一年最多两次（寒暑假各一）」按自然年数。delay_count 是这条持有记录的
            # 终身计数，跨年不清零的话，第二年就再也顺延不了了。
            year = today()[:4]
            used = db.query_one(
                "SELECT COUNT(*) c FROM ledger WHERE member_id=? AND kind='holiday_delay'"
                " AND substr(ts,1,4)=?", (h["member_id"], year))["c"]
            if used >= max_per_year:
                continue
            db.execute("UPDATE holding SET expires_at=?, delay_count=delay_count+1 WHERE id=?",
                       (target, h["id"]))
            add_ledger(h["member_id"], "holiday_delay", ref_type="holding", ref_id=h["id"],
                       note="假期顺延：%s → %s（%s）" % (h["expires_at"], target, hd["name"]),
                       operator_id=operator_id)
            out.append({"item": h["name"], "to": target, "holiday": hd["name"]})
    return out


# ---------------------------------------------------------------------------
# 碎片合成（只朝上换钻石级）
# ---------------------------------------------------------------------------
def exchange_fragments(member_id, mode="random", code=None, operator_id=None):
    """碎片合成：10 片随机一张钻石级，20 片自选一张（第 04 章）。

    「自选」得是真的自选：不带 code 时先把能挑的几张回给前端、不扣碎片，
    带上 code 才扣 20 片把那一张发下去。原来两种档位都走随机，
    等于让孩子多花 10 片买同一个东西。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    if mode not in ("random", "pick"):
        return {"ok": False, "msg": "没有这种合成方式"}
    need = 10 if mode == "random" else 20
    if fragment_balance(member_id) < need:
        return {"ok": False, "msg": "碎片不够，需要 %d 片" % need}

    card = None
    if mode == "random":
        card = pick_card(member_id, "diamond")
    else:
        options = db.query("SELECT * FROM item WHERE category='card' AND rarity='diamond'"
                           " AND active=1 ORDER BY sort")
        if not options:
            return {"ok": False, "msg": "没有钻石级道具可以发"}
        if not code:
            return {"ok": False, "code": "pick", "pickable": True, "need": need,
                    "options": [{"code": o["code"], "name": o["name"]} for o in options],
                    "msg": "先挑一张，再换"}
        card = next((o for o in options if o["code"] == code), None)
        if not card:
            return {"ok": False, "msg": "这一张不是钻石级"}
    if not card:
        return {"ok": False, "msg": "没有钻石级道具可以发"}

    add_ledger(member_id, "fragment", fragment=-need, note="碎片合成（%s）" % mode,
               operator_id=operator_id)
    db.execute("INSERT INTO fragment_use (member_id, qty, kind, note, ts) VALUES (?,?,?,?,?)",
               (member_id, need, "spend", "合成钻石级 " + mode, now()))
    grant_item(member_id, card["id"], 1, source="box", kind="fragment",
               note="碎片合成：%s" % card["name"], operator_id=operator_id)
    return {"ok": True, "card": {"name": card["name"], "code": card["code"]},
            "pickable": mode == "pick", "cost": need}


# ---------------------------------------------------------------------------
# 成长报告
# ---------------------------------------------------------------------------
def growth_report(member_id, days=30):
    days = max(1, min(365, int(days or 30)))
    # 窗口起点用 today() 算，不写 date('now')：SQLite 的真实时钟绕不过
    # freeze_clock，测试里「最近 30 天」会跟别处对不上，而且这个函数是全系统
    # 唯一一处绕过引擎时钟的地方。
    since = fmt(parse_day(today()) - timedelta(days=days))
    rows = db.query(
        "SELECT day, COUNT(*) n, SUM(CASE WHEN value>0 THEN 1 ELSE 0 END) ok FROM score_entry"
        " WHERE member_id=? AND voided=0 AND is_fixed=1 AND day>=?"
        " GROUP BY day ORDER BY day", (member_id, since))
    total = sum(r["n"] for r in rows)
    ok = sum(r["ok"] for r in rows)
    by_dim = db.query(
        "SELECT d.name, SUM(se.value) v, COUNT(*) n FROM score_entry se"
        " JOIN dimension d ON d.id=se.dimension_id"
        " WHERE se.member_id=? AND se.voided=0 AND se.day>=? GROUP BY d.id"
        " ORDER BY d.sort", (member_id, since))
    explores = db.query(
        "SELECT phrase, ts FROM explore WHERE member_id=? ORDER BY id DESC LIMIT 20", (member_id,))
    positives = [r["phrase"] for r in explores if r["phrase"]]
    return {
        "days": days,
        "rate": round(ok / float(total) * 100, 1) if total else 0,
        "checked": total,
        "daily": [{"day": r["day"], "score": r["ok"]} for r in rows],
        "by_dimension": [{"name": r["name"], "score": r["v"],
                          "rate": round(r["v"] / (r["n"] * 1.0) * 100, 1) if r["n"] else 0}
                         for r in by_dim],
        "first_screen": positives[:3],
        "note": "第一屏留给你说过的原话。分数是给家长看的，孩子只看这些。",
    }


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------
def push_notify(member_id, kind, title, body=""):
    """写一条网页通知，顺手叫醒推送线程。

    v20 起这里不只是一个写库动作，而是「所有通知的唯一出口」——
    写库 + 叫醒后台线程，后者把没发过的捡起来推到手机上。
    加推送的时候没有去改那十几个调用点，就是因为它们本来就全走这里。

    member_id 为空表示「球在大人的手上」（券申请、任务待确认这类），
    推送侧会把空值解析成「所有家长」，不是字面意义的全家。
    """
    nid = db.execute("INSERT INTO notification (member_id, kind, title, body, ts)"
                     " VALUES (?,?,?,?,?)", (member_id, kind, title, body, now()))
    N.kick()
    return nid


# ---------------------------------------------------------------------------
# 两个独立事件通道（第 09 / 10 章）
#
# 它们刻意不进打分表：一旦跟每日得分挂钩，孩子会倾向隐藏而不是改善。
# 也刻意不罚钱：罚金那条线只管「说了不算」。两个通道共用的规则是
# 「先查因，再处理」，所以 reason / note 都不是装饰字段。
# ---------------------------------------------------------------------------
def end_due_downgrades():
    """到期的设备降级自动恢复。惰性，不用 cron。"""
    db.execute("UPDATE device_downgrade SET status='ended' WHERE status='active' AND end_date<?",
               (today(),))


def device_downgrade_state(member_id):
    """这个孩子现在是不是「只能用公共区域设备」。"""
    end_due_downgrades()
    r = db.query_one("SELECT * FROM device_downgrade WHERE member_id=? AND status='active'"
                     " ORDER BY id DESC LIMIT 1", (member_id,))
    if not r:
        return {"active": False, "days": 0, "days_left": 0, "end_date": None, "reason": ""}
    left = (parse_day(r["end_date"]) - parse_day(today())).days
    return {"active": True, "id": r["id"], "days": r["days"],
            "start_date": r["start_date"], "end_date": r["end_date"],
            "days_left": max(0, left), "reason": r["reason"]}


def start_device_downgrade(member_id, days=None, reason="", operator_id=None):
    """偷玩游戏：降级，不是没收（第 09 章）。

    没收一周做不到，而且会直接引发对抗，最后往往以家长妥协收场；
    扣券更没道理 —— 他偷玩恰好证明券拦不住他，对一个已经不在规则里的
    人执行规则只会让他下次更隐蔽。

    30 天内重复：降级 3 天延长到 7 天，然后一起调规则（券额度 / 时段 /
    申请通道）。不加重别的惩罚 —— 重复说明的是规则不够用，不是孩子更坏。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    if not is_judge(operator_id):
        return {"ok": False, "msg": JUDGE_MSG}
    end_due_downgrades()
    window = int(db.cfg("steal_game.repeat_window_days", 30))
    since = fmt(parse_day(today()) - timedelta(days=window))
    repeat = db.query_one(
        "SELECT COUNT(*) c FROM device_downgrade WHERE member_id=? AND start_date>=?",
        (member_id, since))["c"] > 0
    if days is None:
        days = int(db.cfg("steal_game.repeat_days", 7)) if repeat else int(db.cfg("steal_game.days", 3))
    days = max(1, min(30, int(days)))
    start = today()
    end = fmt(parse_day(start) + timedelta(days=days))
    # 同一时间只留一条生效的：再记一次是重新计时，不是叠加天数
    db.execute("UPDATE device_downgrade SET status='ended' WHERE member_id=? AND status='active'",
               (member_id,))
    did = db.execute(
        "INSERT INTO device_downgrade (member_id, reason, days, start_date, end_date, status,"
        " operator_id, created_at) VALUES (?,?,?,?,?,'active',?,?)",
        (member_id, reason, days, start, end, operator_id, now()))
    push_notify(member_id, "device", "设备降级 %d 天" % days,
                "到 %s 之前只能在公共区域用%s" % (end, ("：" + reason) if reason else ""))
    return {"ok": True, "id": did, "days": days, "start_date": start, "end_date": end,
            "repeat": bool(repeat),
            "msg": ("30 天内第二次，降到 7 天。这次一起看看规则哪儿卡住了"
                    if repeat else "记下了，%s 自动恢复" % end)}


def revoke_study_score(member_id, day, operator_id=None, subject="", note=""):
    """抄作业事后才被发现：撤掉当日「智识」那 1 分，追加一条作业复核（第 10 章）。

    抄作业通常在第二天核对时才被发现，那时当天分数已经打过了。撤的是
    一个还没被验证的判断（那 1 分本来就不该给），不是已经发出去的东西
    —— 已开出的宝箱、已发的券、已到账的星尘一律不动，所以不算追溯。
    当天其余 6 项也不动。

    这个函数只做「撤分」，不做「讲给我听」。重讲一遍是补课不是惩罚，
    它走修复任务那条线（系统生成、孩子做完、家长确认），不在这里顺手塞。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    if not is_judge(operator_id):
        return {"ok": False, "msg": JUDGE_MSG}
    if not db.cfg("homework.revoke_study", True):
        return {"ok": False, "msg": "这一项已经关掉了"}
    if day > today():
        return {"ok": False, "msg": "还没到这天"}
    cyc = get_or_create_cycle(member_id, day)
    if cyc["status"] == "settled":
        # 结算过就动了别人的账：那个周期的星尘早就算进去了
        return {"ok": False, "msg": "这个周期已经结算，撤不了"}
    dim = db.query_one("SELECT * FROM dimension WHERE code='study'")
    if not dim:
        return {"ok": False, "msg": "没找到「智识」这个维度"}
    row = db.query_one("SELECT * FROM score_entry WHERE member_id=? AND day=? AND dimension_id=?"
                       " AND voided=0", (member_id, day, dim["id"]))
    if not row:
        return {"ok": False, "msg": "这天没有智识分的记录"}
    if float(row["value"] or 0) <= 0:
        return {"ok": False, "msg": "这天智识分本来就是 0，没有可撤的"}
    db.execute("UPDATE score_entry SET voided=1 WHERE id=?", (row["id"],))
    db.execute("INSERT INTO correction (target_type, target_id, before_json, after_json,"
               " actor_id, ts) VALUES ('score_entry',?,?,?,?,?)",
               (row["id"], json.dumps({"value": row["value"], "voided": 0}),
                json.dumps({"value": 0, "voided": 1, "reason": "作业复核"}),
                operator_id, now()))
    before = cyc["fixed_score"] or 0
    after = recalc_cycle(cyc["id"])
    diff = (after["fixed_score"] or 0) - before
    if abs(diff) > 1e-9:
        add_ledger(member_id, "daily_score", cycle_id=cyc["id"], day=day, energy=diff,
                   note="作业复核：撤销 %s 的智识分" % day, operator_id=operator_id)
    db.execute("INSERT INTO homework_check (member_id, day, subject, revoked, note, operator_id,"
               " created_at) VALUES (?,?,?,?,?,?,?)",
               (member_id, day, subject, int(row["value"] or 0), note, operator_id, now()))
    push_notify(member_id, "homework", "作业复核",
                "%s 的智识分撤销 %g 分" % (day, float(row["value"] or 0)))
    return {"ok": True, "revoked": float(row["value"] or 0), "cycle": cycle_snapshot(cyc["id"])}


def card_used_this_cycle(member_id, item_id, cycle_id=None):
    """同类卡本周期用掉几张（第 04 章护栏三）。

    查的是 item_use 而不是余额：余额只说明「手上还有几张」，
    护栏要拦的是「这一周已经用过同一种了」。不查的话，攒 5 张翻倍卡
    一天全用掉这种事就会发生。
    """
    cyc = db.query_one("SELECT * FROM cycle WHERE id=?", (cycle_id,)) if cycle_id \
        else current_cycle(member_id)
    if not cyc:
        return 0.0
    return float(db.query_one(
        "SELECT COALESCE(SUM(qty),0) v FROM item_use WHERE member_id=? AND item_id=?"
        " AND date(ts) BETWEEN ? AND ?",
        (member_id, item_id, cyc["start_date"], cyc["end_date"]))["v"] or 0)


def open_notifications(member_id=None):
    if member_id is None:
        return db.query("SELECT * FROM notification WHERE member_id IS NULL AND read_at IS NULL"
                        " ORDER BY id DESC LIMIT 50")
    return db.query("SELECT * FROM notification WHERE (member_id=? OR member_id IS NULL)"
                    " AND read_at IS NULL ORDER BY id DESC LIMIT 50", (member_id,))


# ---------------------------------------------------------------------------
# 卡片效果（v22）
# ---------------------------------------------------------------------------
# 之前用一张卡 = 库存减一，然后什么都不发生。这张卡的效力到底是「机器自己改」
# 还是「爸爸妈妈去办」，以前没有答案，现在按 effect_key 分成四类：
#
#   FLAG   当天生效的标记。系统会认（免间隔 / 晚睡点），也会在家长那边显示。
#   ARMED  装填。卡先扣掉，等触发它的那件事来了才结算（翻倍 / 重抽 / 后果自选）。
#   MINUTE 直接写分钟账。加时往上加额度，抵扣往下消欠账，都是系统当场就能做的。
#   REDEEM 要真人配合的一律进兑现单，家长点「做到了」才消。漏了这笔账，
#          孩子手里剩下的卡就等于一个数字符号。
#
# 分流的原则是「谁做得到」。 discourses 那种「陪我一个小时」机器永远办不到，
# 硬写成自动生效就是骗人；反过来「加时 30 分钟」机器本来就在算额度，
# 让人去点一下反而多此一举。
FLAG_EFFECTS = ("late_bed", "skip_cooldown", "no_nagging", "skip_chore_day")
ARMED_EFFECTS = ("double_reward", "double_allowance", "reroll_random", "choose_consequence")
MINUTE_EFFECTS = ("extra_minutes", "offset_penalty")

FLAG_TEXT = {
    "late_bed":       "今晚可以晚睡 %d 分钟",
    "skip_cooldown":   "今天用娱乐券不用等两轮之间的间隔",
    "no_nagging":     "今天不催，说到做到",
    "skip_chore_day": "今天免一天额外家务",
}


def _fx(item):
    return json.loads(item["effect_json"] or "{}")


def _flag_placeholders(keys):
    return ",".join("?" * len(keys))


ARMED_TEXT = {'double_reward': '装填好了，下一次拿到星尘的时候翻倍', 'double_allowance': '装填好了，下一次换零花钱的时候多拿一份', 'reroll_random': '装填好了，下一箱开出来的随机件会抽两次，取更好的那个', 'choose_consequence': '装填好了，下一次校准的修复方式由你自己定'}


def use_card(member_id, code, *, operator_id=None, note="", qty=1.0):
    """用一张卡。真正出口只有一个，前端拿到的反馈也是这里给的。

    返回 {'ok': True, 'status': ..., 'message': ...}。message 是给孩子看的，
    必须说清楚接下来会发生什么 —— 以前点了「使用」之后屏幕上只有库存数字
    少了一格，孩子不知道这张卡是当场生效还是在等大人。
    """
    if not is_player(member_id):
        return {"ok": False, "msg": PARENT_MSG}
    it = item_by_code(code)
    if not it:
        return {"ok": False, "msg": "没有这个东西"}
    if it["category"] != "card":
        return {"ok": False, "msg": "券要在「我的」里点核销，等爸爸妈妈点一下"}
    qty = float(qty or 1)
    if qty <= 0:
        return {"ok": False, "msg": "数量不对"}
    if item_balance(member_id, it["id"]) < qty:
        return {"ok": False, "msg": "你手上没有这个（或不够）"}

    # 护栏三：同类卡一个周期最多用一张（第 04 章）
    same_limit = float(db.cfg("card.same_cycle_limit", 1) or 0)
    if same_limit > 0 and card_used_this_cycle(member_id, it["id"]) >= same_limit:
        return {"ok": False, "msg": "「%s」这个周期已经用过了。同类卡一个周期只能用 %d 张"
                                    % (it["name"], int(same_limit))}

    day = today()
    key = it["effect_key"]
    fx = _fx(it)

    # --- 各自的门槛 ---
    if key == "double_stardust_week":
        cyc = current_cycle(member_id)
        if cyc and float(cyc["energy"] or 0) > 0:
            return {"ok": False, "msg": "星尘双倍周必须在周期开始前指定，这一周已经开始了"}
    if key == "offset_penalty":
        debt = minutes_debt(member_id)
        if debt <= 0:
            return {"ok": False, "msg": "现在没有欠着的分钟，" + it["name"] + "留着以后用"}
    if key in FLAG_EFFECTS and card_flag(member_id, key, day):
        return {"ok": False, "msg": "今天的「%s」已经在生效了" % it["name"]}

    # --- 扣库存 ---
    got = consume_item(member_id, it["id"], qty, kind="card_use",
                       note=note or ("使用 " + it["name"]), operator_id=operator_id)
    if got != 0:
        return {"ok": False, "msg": "扣不掉这张卡，稍后再试"}

    # --- 分四类处理 ---
    if key in ARMED_EFFECTS:
        status, msg = "armed", ARMED_TEXT.get(key, "已经装填好了，下一次就生效")
    elif key in FLAG_EFFECTS:
        status = "active"
        m = int(float(fx.get("minutes", 0) or 0))
        t = FLAG_TEXT.get(key, "今天有效")
        msg = (t % m) if "%d" in t else t
    elif key == "extra_minutes":
        status = "done"
        m = float(fx.get("minutes", 0) or 0)
        if m:
            add_ledger(member_id, "card_effect", day=day, minutes=m, ref_type="item",
                       ref_id=it["id"], operator_id=operator_id,
                       note="%s：今天多 %g 分钟" % (it["name"], m))
        msg = "今天多 %g 分钟，已经算进去了" % m
    elif key == "offset_penalty":
        status = "done"
        m = min(float(fx.get("minutes", 0) or 0), minutes_debt(member_id))
        if m:
            add_ledger(member_id, "card_effect", day=day, minutes=m, ref_type="item",
                       ref_id=it["id"], operator_id=operator_id,
                       note="%s：抵消 %g 分钟欠账" % (it["name"], m))
        msg = "抵消了 %g 分钟欠账" % m
    elif key == "double_stardust_week":
        cyc = current_cycle(member_id)
        status = "done"
        db.execute("UPDATE item_use SET meta=? WHERE id=(SELECT MAX(id) FROM item_use)",
                   (json.dumps({"cycle_start": cyc["start_date"] if cyc else day},
                               ensure_ascii=False),))
        msg = "这一周的固定分双倍计入星尘，满勤 +49"
    else:
        status = "pending"
        msg = "已经排给爸爸妈妈了：%s" % (it["desc"] or it["name"])

    rid = db.execute(
        "INSERT INTO card_redeem (member_id, item_id, effect_key, payload, day, status, auto,"
        " created_at, updated_at, note, operator_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (member_id, it["id"], key, json.dumps(fx, ensure_ascii=False), day, status,
         1 if status != "pending" else 0, now(), now(), note or "", operator_id))

    if status == "pending":
        mrow = db.query_one("SELECT name FROM member WHERE id=?", (member_id,))
        who = mrow["name"] if mrow else "孩子"
        push_notify(None, "card", "有卡片要兑现", "%s 用了「%s」，等你们去办" % (who, it["name"]))

    return {"ok": True, "redeem_id": rid, "status": status, "message": msg,
            "name": it["name"], "left": item_balance(member_id, it["id"]),
            "flags": card_flags(member_id), "armed": armed_cards(member_id)}


def card_flag(member_id, effect_key, day=None):
    """当天某一类标记还在不在。"""
    day = day or today()
    return db.query_one(
        "SELECT * FROM card_redeem WHERE member_id=? AND day=? AND effect_key=?"
        " AND status='active' ORDER BY id DESC LIMIT 1", (member_id, day, effect_key))


def card_flag_minutes(member_id, effect_key, day=None):
    """晚睡卡今天批了多少分钟。同一周期的同类卡限一张，所以最多一行。"""
    r = card_flag(member_id, effect_key, day)
    if not r:
        return 0.0
    return float(json.loads(r["payload"] or "{}").get("minutes", 0) or 0)


def card_flags(member_id, day=None):
    """今天在生效的卡片效果。给家长看，也给 Bedroom / 闸门用。

    返回的是人话，不是 effect_key —— 家长扫一眼就该知道今天对这个孩子
    有哪几条例外。
    """
    day = day or today()
    out = []
    for r in db.query("SELECT * FROM card_redeem WHERE member_id=? AND day=? AND status='active'"
                      " ORDER BY id", (member_id, day)):
        it = db.query_one("SELECT name, icon FROM item WHERE id=?", (r["item_id"],))
        if not it:
            continue
        mins = int(float(json.loads(r["payload"] or "{}").get("minutes", 0) or 0))
        t = FLAG_TEXT.get(r["effect_key"], "今天有效")
        if "%d" in t:
            t = t % mins
        out.append({"key": r["effect_key"], "name": it["name"], "icon": it["icon"] or "",
                    "text": t, "minutes": mins, "day": r["day"]})
    return out


def armed_cards(member_id):
    """装填中还没用掉的卡。前端要告诉孩子「这张卡已经在等着了」，
    不然他不知道自己刚才点的那一下到底有没有生效。
    """
    out = []
    for r in db.query("SELECT * FROM card_redeem WHERE member_id=? AND status='armed'"
                      " ORDER BY id", (member_id,)):
        it = db.query_one("SELECT name, icon, desc FROM item WHERE id=?", (r["item_id"],))
        if not it:
            continue
        out.append({"key": r["effect_key"], "name": it["name"], "icon": it["icon"] or "",
                    "desc": it["desc"] or "", "since": r["day"]})
    return out


def consume_armed(member_id, effect_key):
    """装填的卡在今天这件事上用掉。返回 payload，没有装填返回 None。

    取最早那一张：孩子攒了两张翻倍卡，先用先前的那张，符合直觉。
    """
    r = db.query_one("SELECT * FROM card_redeem WHERE member_id=? AND effect_key=?"
                     " AND status='armed' ORDER BY id LIMIT 1", (member_id, effect_key))
    if not r:
        return None
    db.execute("UPDATE card_redeem SET status='done', done_at=?, updated_at=? WHERE id=?",
               (now(), now(), r["id"]))
    return json.loads(r["payload"] or "{}")


def pending_redeems(member_id=None, limit=100):
    """等爸爸妈妈兑现的卡。家长的待办里要能数到它们。"""
    sql = ("SELECT r.*, i.name, i.icon, i.rarity, i.desc AS item_desc, m.name AS member_name,"
           " m.avatar FROM card_redeem r JOIN item i ON i.id=r.item_id"
           " JOIN member m ON m.id=r.member_id WHERE r.status='pending'")
    args = []
    if member_id:
        sql += " AND r.member_id=?"
        args.append(member_id)
    sql += " ORDER BY r.id DESC LIMIT ?"
    args.append(int(limit))
    rows = db.query(sql, args)
    return [{"id": r["id"], "member_id": r["member_id"], "member_name": r["member_name"],
             "avatar": r["avatar"], "item_name": r["name"], "icon": r["icon"] or "",
             "rarity": r["rarity"], "effect_key": r["effect_key"],
             "desc": r["item_desc"] or "", "day": r["day"], "note": r["note"],
             "created_at": r["created_at"]} for r in rows]


def finish_redeem(redeem_id, operator_id=None, note="", done=True):
    """家长点「做到了」/「这次没兑现」。

    没兑现的那条退回 pending 吗？不退回 —— 卡已经消耗掉了，退回去家长就得
    自己记「这张没用」。所以这里只记一句说明，事情本身留在孩子的执念里：
    下一次他会不会攒卡，取决于这次大人有没有当回事。
    """
    r = db.query_one("SELECT * FROM card_redeem WHERE id=?", (int(redeem_id),))
    if not r:
        return {"ok": False, "msg": "没有这条兑现单"}
    if r["status"] != "pending":
        return {"ok": False, "msg": "这条已经处理过了"}
    db.execute("UPDATE card_redeem SET status=?, done_at=?, updated_at=?, operator_id=?, note=?"
               " WHERE id=?", ("done" if done else "void", now(), now(), operator_id,
                               note or "", r["id"]))
    it = db.query_one("SELECT name FROM item WHERE id=?", (r["item_id"],))
    if done:
        push_notify(r["member_id"], "card", "卡片兑现完成",
                    "「%s」爸爸妈妈已经兑现了" % (it["name"] if it else "卡片"))
    return {"ok": True, "status": "done" if done else "void"}


