# -*- coding: utf-8 -*-
"""国家法定节假日日历：家长手动拉一份公开数据进来，回答「这天放不放假」。

只在家长点按钮的时候出网
------------------------
这套系统默认跑在 NAS 的 Docker 里，很多人的容器根本没有外网。所以这里
没有任何自动同步：不开机拉、不每天拉、不后台线程里拉。表是空的就一直
是空的，判定退回「只看周六周日」，系统照常能用。

想更新，就到家长端「设置 → 周期与假期 → 假期日历」，点那颗「立即更新
国家日历」。那一刻发的是一次普通的 HTTPS GET，走的是标准库，没装任何
第三方包。

为什么要这张表
--------------
判定「放不放假」的用处有两处，共用同一个答案：娱乐券面值翻不翻倍，
硬停止放到几点。以前两处都只看「是不是周六周日」，于是调休上班的那个
周末两头都错 —— 那天要上学，却既给翻倍又放宽到 22:00。

数据源
------
NateScarlet/holiday-cn，从国务院放假安排的原文扒下来的，文件里带
papers 字段指向原文链接，能回溯。每年国务院发文（通常前一年 11 月）
之后仓库才更新，所以 2027 那一份现在是空的，这是正常的，不是坏了。

三个镜像轮流试，全失败就什么都不做。拉不到日历不能让家里这台机器
报错，更不能退化成「一律不放假」—— 那样等于把已经拉到的数据废掉。

不回答什么
----------
寒暑假不在这里。全国没有统一数据，各校自己定，那部分继续走 holiday 表
家长手填。这一份只认国务院那张安排表。
"""

import json
import urllib.error
import urllib.request

import db

TIMEOUT = 5          # 秒。家庭网络慢的时候宁可跳过，也不能卡住服务
MAX_YEARS_AHEAD = 1  # 今年 + 明年

# 三个镜像，按顺序试。第三个（raw.githubusercontent）在国内偏慢，
# 只作兜底，所以放最后。
SOURCES = (
    "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)


def _get(url):
    """取一份 JSON。任何问题都返回 None —— 网络这件事不该影响家里的账。"""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "family-points/1", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def fetch_year(year):
    """拉某一年的日历。返回 (days, source)，days 是 {day: (is_off, name)}。

    拉不到、或者拉到的是空表（国务院还没发文），都返回 (None, None)。
    空表尤其不能当成「这一年天天上学」写进库 —— 那是把好数据冲掉。
    """
    for tpl in SOURCES:
        data = _get(tpl.format(year=year))
        if not isinstance(data, dict):
            continue
        rows = data.get("days")
        if not isinstance(rows, list):
            continue
        if not rows:
            # 这一年国务院还没发文（通常前一年 11 月才发），文件在、内容空。
            # 这是正常的，不是这个源坏了，别再花 5 秒去敲下一个镜像 ——
            # 家长点「立即更新」要等 15 秒的话，按钮就像卡住了。
            return None, None
        out = {}
        for r in rows:
            d = str(r.get("date") or "")[:10]
            if len(d) != 10:
                continue
            out[d] = (1 if r.get("isOffDay") else 0, str(r.get("name") or ""))
        if out:
            return out, tpl.format(year=year)
    return None, None


def sync_year(year):
    """把某一年写进库。返回写进去的天数，没拉到返回 0。"""
    year = int(year)
    days, src = fetch_year(year)
    if not days:
        return 0
    ts = db.now()
    for d in sorted(days):
        is_off, name = days[d]
        db.execute(
            "INSERT INTO calendar_day (day, is_off, name, year, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(day) DO UPDATE SET is_off=excluded.is_off,"
            " name=excluded.name, year=excluded.year, updated_at=excluded.updated_at",
            (d, is_off, name, year, ts))
    return len(days)


def sync(force=True):
    """拉今年和明年。返回一份够界面直接显示的回执。

    这是唯一会出网的入口，只有家长点「立即更新」才会走到。重拉不做
    「这一年库里已经有就跳过」的短路 —— 手动点一次就是想拿最新的，
    一年也就点一两回，不值得为省一次 CDN 请求把年中调整的机会堵死。

    「上次什么时候拉的」不另存设置项：从表里 MAX(updated_at) 直接读。
    多存一份就要多一处同步，万一两边对不上，界面上那句话就成了骗人的。
    """
    y0 = int(db.today()[:4])
    got = 0
    for y in range(y0, y0 + MAX_YEARS_AHEAD + 1):
        got += sync_year(y)
    state = state_of()
    state["fetched"] = got
    return state


def state_of():
    """界面要显示的那几项：上次什么时候拉的、覆盖了哪几年、库里多少天。"""
    total = db.query_one("SELECT COUNT(*) c, MAX(updated_at) t FROM calendar_day")
    off = db.query_one("SELECT COUNT(*) c FROM calendar_day WHERE is_off=1")
    years = [str(r["year"]) for r in
             db.query("SELECT DISTINCT year FROM calendar_day ORDER BY year")]
    return {
        "last_at": (total["t"] if total and total["t"] else "") or "",
        "years": years,
        "days": int(total["c"]) if total else 0,
        "off_days": int(off["c"]) if off else 0,
    }


def today_state():
    """今天在国家日历里是什么身份，界面上要说得出口。

    三种：法定假日、调休上班、都不算（普通日子）。前两种才有话说，
    第三种不打扰。
    """
    r = db.query_one("SELECT is_off, name FROM calendar_day WHERE day=?", (db.today(),))
    if not r:
        return None
    return {"day": db.today(), "is_off": bool(r["is_off"]), "name": r["name"] or ""}
