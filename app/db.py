# -*- coding: utf-8 -*-
"""
数据库访问层。

单文件 SQLite，WAL 模式。所有连接按线程缓存（http.server 是多线程的）。
"""
import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta

import seed_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FAMILY_DATA_DIR") or os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("FAMILY_DB") or os.path.join(DATA_DIR, "family.db")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")

_local = threading.local()
_init_lock = threading.Lock()
_written = set()


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        _local.conn = conn
    return conn


def query(sql: str, args=()) -> list:
    cur = get_conn().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return rows


def query_one(sql: str, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args=()) -> int:
    conn = get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    lastrow = cur.lastrowid
    cur.close()
    return lastrow


def executemany(sql: str, seq) -> None:
    conn = get_conn()
    conn.executemany(sql, seq)
    conn.commit()


def to_dict(row) -> dict:
    return dict(row) if row is not None else None


def to_dicts(rows) -> list:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 建表 + 种子
# ---------------------------------------------------------------------------
def init_db(verbose: bool = False):
    """建表并灌入默认值。可重复调用，不会覆盖用户已经改过的内容。"""
    with _init_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        schema = open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8").read()
        conn = get_conn()
        conn.executescript(schema)
        conn.commit()
        _seed(conn, verbose=verbose)


def _builtin_start_date(conn):
    """建库那天。起用日（family.start_date）的默认值就是它。

    取成员表里最早那条记录的时间 —— 成员是建库时跟着灌进去的，所以它就等于
    建库那一刻；老库升级上来取值同样落在当初建库那天。还没有成员就用此刻。
    """
    row = conn.execute("SELECT MIN(created_at) v FROM member").fetchone()
    d = str((row[0] if row else "") or "")[:10]
    return d if len(d) == 10 else now()[:10]


def _seed(conn, verbose: bool = False):
    log = (lambda m: print(m)) if verbose else (lambda m: None)

    # 成员
    n = conn.execute("SELECT COUNT(*) FROM member").fetchone()[0]
    if n == 0:
        conn.executemany(
            "INSERT INTO member (name, role, avatar, sort, active, created_at) VALUES (?,?,?,?,1,?)",
            [(nm, rl, av, st, now()) for nm, rl, av, st in seed_data.MEMBERS],
        )
        log("  成员 4 位")

    # 维度
    n = conn.execute("SELECT COUNT(*) FROM dimension").fetchone()[0]
    if n == 0:
        conn.executemany(
            "INSERT INTO dimension (code, name, holiday_name, meaning, icon, score, sort) VALUES (?,?,?,?,?,1,?)",
            seed_data.DIMENSIONS,
        )
        log("  维度 7 个")

    # 宝箱档位
    n = conn.execute("SELECT COUNT(*) FROM box_tier").fetchone()[0]
    if n == 0:
        for t in seed_data.BOX_TIERS:
            tier, code, name, thr, tk, sd, rate, cards, dr, price = t
            pool = seed_data.BOX_RANDOM_POOL.get(code, [])
            conn.execute(
                """INSERT INTO box_tier
                   (tier, code, name, threshold, tickets, stardust, random_rate, random_pool,
                    cards_json, card_rarity, card_count, diamond_rate, purchase_price,
                    purchase_allowed, icon, sort)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tier, code, name, thr, tk, sd, rate, json.dumps(pool, ensure_ascii=False),
                 json.dumps([{"rarity": r, "count": c} for r, c in cards], ensure_ascii=False),
                 cards[0][0] if cards else "", sum(c for _, c in cards), dr, price,
                 1 if price else 0,
                 seed_data.BOX_ICONS.get(tier, ""), tier),
            )
        log("  宝箱 7 档")

    # 道具图鉴
    n = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    if n == 0:
        idx = 0
        for code, name, rarity, ekey, ejson, desc in seed_data.CARDS:
            idx += 1
            conn.execute(
                """INSERT INTO item
                   (code, name, category, rarity, card_no, price, purchasable, weekly_limit,
                    shelf_life_days, max_hold, renew_cost_pct, renew_times, expire_refund,
                    fragment_value, transferable, effect_key, effect_json, desc, icon, sort, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (code, name, "card", rarity, "C-%02d" % idx,
                 seed_data.PRICE[rarity], 0,
                 seed_data.MAXHOLD[rarity] and 1,
                 seed_data.SHELF[rarity], seed_data.MAXHOLD[rarity], 20, 1,
                 seed_data.REFUND[rarity], seed_data.FRAG[rarity], 0,
                 ekey, json.dumps(ejson, ensure_ascii=False), desc,
                 seed_data.ITEM_ICONS.get(code, ""), idx),
            )
        for i, (code, name, price, wl, minutes, trans, ejson, desc) in enumerate(seed_data.TICKETS, 1):
            conn.execute(
                """INSERT INTO item
                   (code, name, category, rarity, card_no, price, purchasable, weekly_limit,
                    shelf_life_days, max_hold, renew_cost_pct, renew_times, expire_refund,
                    fragment_value, transferable, effect_key, effect_json, desc, icon, sort, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (code, name, "ticket", "", "T-%02d" % i, price,
                 1 if code in seed_data.SHOP_TICKETS else 0, wl, None, None, 20, 0, 0, 0,
                 trans, "ticket", json.dumps(ejson, ensure_ascii=False), desc,
                 seed_data.ITEM_ICONS.get(code, ""), 100 + i),
            )
        log("  道具 23 张卡 + 6 种券")

    # 设置项。老库不能只靠「表为空」来判断：每次升级都可能新增设置项
    # （v13 加了星球等级表），所以要按 key 补差集。已有的 key 一律不碰，
    # 家里自己改过的价格、门槛、额度不会被升级冲掉。
    have = set(r[0] for r in conn.execute("SELECT key FROM setting"))
    added = 0
    for (k, v, t, g, l, note, s, lk) in seed_data.SETTINGS:
        if k in have:
            continue
        if v == seed_data.BOOT_DATE_SENTINEL:
            v = _builtin_start_date(conn)     # 起用日默认落在建库那天
        conn.execute(
            """INSERT INTO setting (key, value, vtype, grp, label, note, sort, editable, locked, updated_at)
               VALUES (?,?,?,?,?,?,?,1,?,?)""",
            (k, json.dumps(v, ensure_ascii=False), t, g, l, note, s, lk, now()))
        added += 1
    if added:
        log("  设置项新增 %d 条" % added)

    # 升级里被撤掉的设置项，留着会在设置页显示成一项没人认识的配置
    for k in seed_data.RETIRED_SETTINGS:
        conn.execute("DELETE FROM setting WHERE key=?", (k,))

    # 修复任务模板存进设置，方便前端取
    row = conn.execute("SELECT 1 FROM setting WHERE key='repair.templates'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO setting (key, value, vtype, grp, label, note, sort, editable, locked, updated_at)"
            " VALUES ('repair.templates','%s','json','校准与修复','修复任务模板',"
            "'系统生成修复任务时用的四类模板。','9',1,0,'%s')"
            % (json.dumps(seed_data.REPAIR_TEMPLATES, ensure_ascii=False).replace("'", "''"), now())
        )

    _migrate_v13(conn)
    _migrate_v14(conn)
    _migrate_v15(conn)
    _migrate_v17(conn)
    _migrate_v18(conn)
    _migrate_v19(conn)
    _migrate_v20(conn)
    _migrate_v21(conn)
    _migrate_v22(conn)
    _migrate_v23(conn)
    _migrate_v24(conn)
    _migrate_v25(conn)
    _migrate_v26(conn)
    _migrate_v29(conn)
    _migrate_v30(conn)
    _migrate_v31(conn)
    _migrate_v32(conn)
    _migrate_v33(conn)
    _migrate_v34(conn)
    _migrate_v35(conn)
    _migrate_v36(conn)
    _migrate_v37(conn)
    _migrate_v38(conn)
    _migrate_v39(conn)
    _migrate_v40(conn)
    _migrate_v41(conn)
    _migrate_v42(conn)
    _migrate_v43(conn)

    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                 (seed_data.SCHEMA_VERSION,))
    conn.commit()


def _migrate_v13(conn):
    """v12 里家长也是玩家，老库里留着一堆家长的周期、流水、宝箱、券卡。

    v13 起家长只打分，不进游戏循环。引擎层已经拦住了新写入，
    但存量的行如果不清掉，结算和历史里会一直冒出「爸爸那周」这种记录。
    按 role 反向删一遍，幂等；新库上什么都不做。家长名下的东西本来就
    是系统自动发的，不是他自己挣的，删掉不损失任何真实数据。
    """
    victims = [r[0] for r in conn.execute("SELECT id FROM member WHERE role!='child'")]
    if not victims:
        return
    q = ",".join("?" * len(victims))
    for sql in (
        "DELETE FROM ledger_item WHERE member_id IN (%s)" % q,
        "DELETE FROM ledger WHERE member_id IN (%s)" % q,
        "DELETE FROM box_open WHERE member_id IN (%s)" % q,
        "DELETE FROM holding WHERE member_id IN (%s)" % q,
        "DELETE FROM item_use WHERE member_id IN (%s)" % q,
        "DELETE FROM fragment_use WHERE member_id IN (%s)" % q,
        "DELETE FROM score_entry WHERE member_id IN (%s)" % q,
        "DELETE FROM explore WHERE member_id IN (%s)" % q,
        "DELETE FROM cycle WHERE member_id IN (%s)" % q,
    ):
        try:
            conn.execute(sql, victims)
        except sqlite3.OperationalError:
            pass          # 早期库没有这张表，跳过


def _ensure_column(conn, table, column, decl):
    """给已有表补一个新列。

    老库上 `CREATE TABLE IF NOT EXISTS` 是空操作，新增的列不会自己出现，
    所以每次加列都得在这里补一句。用 PRAGMA 先问一遍，幂等。
    """
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    except sqlite3.OperationalError:
        return False                  # 表都还没建出来，schema 会负责
    if not have or column in have:
        return False
    conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
    return True


def _migrate_v14(conn):
    """v14：券核销加了五道闸门和家长点头，加时批准后要记「被哪次核销用掉了」。

    新库走 schema.sql 就有这一列；老库得在这里补。
    """
    _ensure_column(conn, "overtime_request", "consumed_by", "INTEGER")

    # 娱乐券的说明里原来写着「单次最多 3 张，两轮之间隔 1 小时，20:30 后最多 2 张」。
    # 这三条现在都是设置项，继续挂在文案上就是一句会过期的谎。
    # 只在它还是那句原文时才换 —— 家长自己改过的话，别动。
    old = "换 30 分钟屏幕时间。单次最多 3 张，两轮之间隔 1 小时，20:30 后最多 2 张。"
    conn.execute("UPDATE item SET desc=? WHERE code='ticket_fun' AND desc=?",
                 ("换 30 分钟屏幕时间。能换几张、几点收工按家里的设置来，"
                  "用之前会告诉你现在行不行。", old))


def _task_ddl_v15():
    """从 schema.sql 里取 task 表定义，改名为 task_new 供重建使用。

    迁移要重建表，但表定义只能有一份真身（在 schema.sql）。
    这里现取现用，免得两边各写一份、改一处漏一处。
    """
    schema = open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8").read()
    m = re.search(r"CREATE TABLE IF NOT EXISTS task \((.*?)\n\);", schema, re.S)
    if not m:
        return None
    return "CREATE TABLE task_new (%s\n)" % m.group(1)


def _migrate_v15(conn):
    """v15：任务大厅。

    大厅里挂着的任务还没有主人，所以 assignee_id 要从 NOT NULL 放开成可空。
    SQLite 改列约束只能重建表（新建 → 搬数据 → 删旧 → 改名），好在老库里
    这一列本来就不为 NULL，搬过去不会丢东西。
    """
    try:
        cols = {r[1]: r for r in conn.execute("PRAGMA table_info(task)")}
    except sqlite3.OperationalError:
        return
    if not cols:
        return

    if cols["assignee_id"][3]:                 # notnull == 1，老库
        ddl = _task_ddl_v15()
        if ddl:
            keep = [c for c in cols if c not in ("slots", "hall_id", "claimed_at")]
            names = ", ".join(keep)
            conn.execute(ddl)
            conn.execute(
                "INSERT INTO task_new (%s, slots, hall_id, claimed_at)"
                " SELECT %s, 1, NULL, NULL FROM task" % (names, names))
            conn.execute("DROP TABLE task")
            conn.execute("ALTER TABLE task_new RENAME TO task")
            return
    # 已经放开过（新库走 schema.sql，或者上面刚重建完），只补缺的列
    _ensure_column(conn, "task", "slots", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "task", "hall_id", "INTEGER")
    _ensure_column(conn, "task", "claimed_at", "TEXT")


def _migrate_v17(conn):
    """v17：孩子也能许愿了，心愿多了一个「挂起等定条件」的阶段。

    只需要两个新列，不用重建表：老库里所有心愿都是家长建的、当场生效，
    补上 configured_at 让它们的进度从建的那天开始算，行为跟以前一致。
    """
    _ensure_column(conn, "wish", "configured_at", "TEXT")
    _ensure_column(conn, "wish", "configured_by", "INTEGER")
    # 存量心愿都是「生下来就带条件」的，没有条件留空却是 active 的。
    # 把生成时刻认成定条件时刻，这样 task_count 那条进度有个起点，
    # 不会因为 configured_at 为空而从「很久以前」开始数。
    conn.execute("UPDATE wish SET configured_at=created_at"
                 " WHERE configured_at IS NULL AND status IN ('active','achieved','claimed')")


def _migrate_v18(conn):
    """v18：心愿历史要分得清「被驳回」和「自己放弃」。

    老库里结束的心愿只有一句 cancelled，看不出是谁结束的、结束前是哪个状态。
    补法用现成的信息推：条件没定过（configured_at 为空）说明当时还挂在墙上，
    那就是被驳回；定过条件的是从「进行中」结束的，算撤回/放弃。
    谁点的这一下老数据里没存，留空，界面上退化成一句「已结束」——
    猜一个名字填上去，比留空更坏。
    """
    _ensure_column(conn, "wish", "closed_by", "INTEGER")
    _ensure_column(conn, "wish", "closed_from", "TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "UPDATE wish SET closed_from=CASE WHEN configured_at IS NULL THEN 'wished' ELSE 'active' END"
        " WHERE status='cancelled' AND (closed_from IS NULL OR closed_from='')")


def _migrate_v19(conn):
    """v19：登录从「点名字 + 可选 PIN」换成「账号 + 密码」。

    老库里没有账号密码，只有一张张能点进去的头像。迁移要解决三件事：
    ① 每个现有成员给一个账号名，默认就用他的名字（家里人自己看得懂），
       重名才加序号 —— 账号名是要天天输入的，用「c1/c2」这种没人记得住。
    ② 认一位管理员。没有管理员就没人能开账号，所以必须现指一个：
       取排序最靠前的家长。之后可以在界面上转移。
    ③ 密码**故意留空**，不清空也不猜。留空会让登录页进入「首次设置」，
       由本人在自己机器上设第一个密码。系统凭空生成一个全家的统一密码，
       等于把密码写在说明书上；不设密码直接放行，那登录就是装饰。
    """
    _ensure_column(conn, "member", "username", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "member", "password_hash", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "member", "is_admin", "INTEGER NOT NULL DEFAULT 0")

    rows = conn.execute(
        "SELECT id, name FROM member WHERE active=1 AND (username IS NULL OR username='')"
        " ORDER BY sort, id").fetchall()
    used = {r[0] for r in conn.execute(
        "SELECT username FROM member WHERE username IS NOT NULL AND username!=''")}
    for mid, name in rows:
        base = (name or ("成员%d" % mid)).strip()
        uname, n = base, 1
        while uname in used:
            n += 1
            uname = "%s%d" % (base, n)
        used.add(uname)
        conn.execute("UPDATE member SET username=? WHERE id=?", (uname, mid))

    has_admin = conn.execute(
        "SELECT COUNT(*) FROM member WHERE is_admin=1 AND active=1").fetchone()[0]
    if not has_admin:
        first = conn.execute(
            "SELECT id FROM member WHERE role='parent' AND active=1 ORDER BY sort, id LIMIT 1"
        ).fetchone()
        if not first:                       # 一个家长都没有就退而求其次，总得有人管
            first = conn.execute(
                "SELECT id FROM member WHERE active=1 ORDER BY sort, id LIMIT 1").fetchone()
        if first:
            conn.execute("UPDATE member SET is_admin=1 WHERE id=?", (first[0],))

    # 老库从没写过 password_hash，这里保持空。已经设过的（重复跑迁移）不动。


def _migrate_v20(conn):
    """v20：通知可以推手机了。

    表结构（push_target）由 schema.sql 的 CREATE TABLE IF NOT EXISTS 负责，
    老库跑一次 init_db 就补上了。这里只管给 notification 加三列：
    这三列是「发没发出去」的唯一凭据，pushed_at 为空才发，
    重试三次还失败就写 push_error 停手，不反复轰炸。

    存量通知一律不补推：那是升级之前发生在网页里的事，
    现在把它们翻出来挨个发到手机上，等于升级当天给全家发一遍旧账。
    判断「是不是刚加上这一列」用 _ensure_column 的返回值，它加完就返回 True，
    第二次跑返回 False —— 迁移链每次 init_db 都会全跑一遍，必须这么判才幂等。
    """
    _ensure_column(conn, "notification", "push_tries", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "notification", "push_error", "TEXT NOT NULL DEFAULT ''")
    # 心愿进度「报过没有」。存周期起点日，不是时刻，理由见 engine.check_wish_ready。
    _ensure_column(conn, "wish", "ready_notified_at", "TEXT NOT NULL DEFAULT ''")
    if _ensure_column(conn, "notification", "pushed_at", "TEXT"):
        conn.execute("UPDATE notification SET pushed_at=ts")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_notification_unpushed ON notification (pushed_at)")


def _migrate_v21(conn):
    """v21：图标自选。

    三件事，按这个顺序：
      1. 补列。task / wish / box_tier 各加一个 icon。
      2. 回填已经存在的宝贝：item 表那 29 条道具在 v21 之前是空的，
         不填的话图鉴会退化成一整屏同一个占位圈。BOX_ICONS / ITEM_ICONS
         按 code 和 tier 索引，逐个 UPDATE。
      3. 只填空的。家长自己改过的图标不能被升级冲掉，所以一律加
         WHERE icon=''。这也保证幂等 —— 迁移链每次 init_db 都全跑一遍。

    图标配对规则只写在一处（seed_data.ITEM_ICONS / BOX_ICONS），这里是它的执行端。
    新库由 _seed 写入，老库由这段回填，两边同一个来源，不会写着写着配成对不上。
    """
    for table in ("task", "wish", "box_tier"):
        _ensure_column(conn, table, "icon", "TEXT NOT NULL DEFAULT ''")

    for tier, tok in sorted(seed_data.BOX_ICONS.items()):
        conn.execute("UPDATE box_tier SET icon=? WHERE tier=? AND icon=''", (tok, tier))

    for code, tok in seed_data.ITEM_ICONS.items():
        conn.execute("UPDATE item SET icon=? WHERE code=? AND icon=''", (tok, code))

    # 维度：把上一版的七个汉字换成对应的图形。
    # 只认那七个具体的字，不认「任意一个字」—— 家长有可能把某个维度改成了
    # 「琴」「跑」这类自己挑的字，那是他改过的数据，升级不能动。
    # 汉字本身依然是合法图标（选择器里单占一组），想换回汉字随时可以。
    OLD_DIM_ICON = {"心": "dim_heart", "智": "dim_study", "力": "dim_vigor",
                    "伴": "dim_bond", "匠": "dim_craft", "洁": "dim_clean",
                    "序": "dim_order"}
    for old, new in OLD_DIM_ICON.items():
        conn.execute("UPDATE dimension SET icon=? WHERE icon=?", (new, old))

    # 兜底：一个字都没有的情况（手抖清空、或者从别的库导过来丢了列）。
    # 正常流程到不了这里，留着是为了不让页面出现空图标。
    for row in conn.execute("SELECT code, icon FROM dimension").fetchall():
        if (row[1] or "").strip():
            continue
        for code, _n, _hn, _mean, icon, _sort in seed_data.DIMENSIONS:
            if code == row[0]:
                conn.execute("UPDATE dimension SET icon=? WHERE code=?", (icon, row[0]))
                break


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------
def snapshot(keep_days: int = 30):
    """SQLite 在线备份，保留最近若干天。每天第一次调用时生成。"""
    if not os.path.exists(DB_PATH):
        return None
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    stamp = today()
    target = os.path.join(SNAPSHOT_DIR, "family-%s.db" % stamp)
    if stamp in _written or os.path.exists(target):
        return target
    src = get_conn()
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    _written.add(stamp)
    # 清理过期快照
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in os.listdir(SNAPSHOT_DIR):
        if not f.endswith(".db"):
            continue
        p = os.path.join(SNAPSHOT_DIR, f)
        try:
            if datetime.fromtimestamp(os.path.getmtime(p)) < cutoff:
                os.remove(p)
        except OSError:
            pass
    return target


def export_json() -> dict:
    """整库导出，用于一键备份。"""
    tables = ["member", "setting", "dimension", "cycle", "score_entry", "ledger", "ledger_item",
              "item", "holding", "box_tier", "box_open", "explore", "wish", "wish_pool",
              "wish_pool_entry", "wish_pool_log", "task", "calibration", "holiday",
              "calendar_day", "help_request",
              "overtime_request", "notification", "fragment_use", "item_use", "audit_log"]
    out = {"exported_at": now(), "schema_version": seed_data.SCHEMA_VERSION}
    for t in tables:
        try:
            out[t] = to_dicts(query("SELECT * FROM %s" % t))
        except sqlite3.Error:
            out[t] = []
    return out


# ---------------------------------------------------------------------------
# 设置读写
# ---------------------------------------------------------------------------
_cache = {}


def settings_all(force: bool = False) -> dict:
    global _cache
    if _cache and not force:
        return _cache
    out = {}
    for r in query("SELECT key, value, vtype FROM setting"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError):
            out[r["key"]] = r["value"]
    _cache = out
    return out


def cfg(key: str, default=None):
    v = settings_all().get(key, default)
    return default if v is None else v


def _needs_double_confirm():
    """改设置要不要另一位家长点头。

    开关默认关（v23）：家里通常只有一个人管这些数字，开着只是给自己多一道手续。
    开了之后还得家里真的有两位家长才走双人 —— 只有一位时进待确认就是死锁，
    那条变更永远等不到一个「不是自己」的人来确认它。
    """
    if not cfg("ops.settings_double_confirm", False):
        return False
    n = query_one("SELECT COUNT(*) c FROM member WHERE role='parent' AND active=1")["c"]
    return int(n or 0) >= 2


def set_setting(key: str, value, actor_id=None, approve=False):
    """写设置。locked 的项拒绝写入。返回 (ok, message)。"""
    row = query_one("SELECT * FROM setting WHERE key=?", (key,))
    if not row:
        return False, "设置项不存在"
    if row["locked"]:
        return False, "这是红线项，改不了"
    if not row["editable"]:
        return False, "这一项不可修改"
    new_val = json.dumps(value, ensure_ascii=False)
    if row["value"] == new_val:
        return True, "值未变化"
    if _needs_double_confirm() and not approve:
        execute(
            "INSERT INTO setting_change (key, old_value, new_value, actor_id, status, ts)"
            " VALUES (?,?,?,?,'pending',?)", (key, row["value"], new_val, actor_id, now()))
        execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, before_json,"
                " after_json, ts) VALUES (?,'setting.propose','setting',NULL,?,?,?)",
                (actor_id, row["value"], new_val, now()))
        return True, "已提交，需另一位家长确认后生效"
    execute("UPDATE setting SET value=?, updated_at=? WHERE key=?", (new_val, now(), key))
    execute("INSERT INTO audit_log (actor_id, action, target_type, target_id, before_json,"
            " after_json, ts) VALUES (?,'setting.update','setting',NULL,?,?,?)",
            (actor_id, row["value"], new_val, now()))
    settings_all(force=True)
    return True, "已更新"


def _migrate_v22(conn):
    """v22：卡片效果 + 分钟账按天结。

    三件事：
      1. card_redeem 表。schema.sql 里已经写了 CREATE IF NOT EXISTS，
         这里再写一遍是为了那种「只还原了旧备份」的场景，迁移链要能自己补齐。
      2. username 唯一。之前两个人可能撞号：登录按 username 查第一行，
         撞号就等于一个人能登进另一个人的账号。这里先把撞名的改开
         （保留排序最靠前那个），再建部分唯一索引；空账号不参与，
         因为「还没开通」的那个空值本来就该允许有多个。
         索引不写在 schema.sql 里是故意的：建表那一步在建索引之前跑，
         万一库里已经有重复的行，executescript 会在启动时就炸掉整个应用。
      3. 分钟账改为按天结 —— 那是引擎逻辑，不用动数据；这里只是把版本号抬上去。
    """
    conn.execute("CREATE TABLE IF NOT EXISTS card_redeem ("
                 " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                 " member_id INTEGER NOT NULL REFERENCES member(id),"
                 " item_id INTEGER NOT NULL REFERENCES item(id),"
                 " effect_key TEXT NOT NULL,"
                 " payload TEXT NOT NULL DEFAULT '{}',"
                 " day TEXT NOT NULL,"
                 " status TEXT NOT NULL DEFAULT 'pending',"
                 " auto INTEGER NOT NULL DEFAULT 0,"
                 " created_at TEXT NOT NULL,"
                 " updated_at TEXT NOT NULL,"
                 " done_at TEXT,"
                 " operator_id INTEGER,"
                 " note TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_card_redeem_status ON card_redeem (status, day)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_card_redeem_member"
                 " ON card_redeem (member_id, effect_key, status)")

    dup = conn.execute(
        "SELECT username, COUNT(*) c, MIN(sort) ms, MIN(id) mi FROM member"
        " WHERE username IS NOT NULL AND username!='' GROUP BY username HAVING c>1").fetchall()
    for uname, _c, msort, keep in dup:
        others = conn.execute(
            "SELECT id FROM member WHERE username=? AND id<>? ORDER BY sort, id",
            (uname, keep)).fetchall()
        for i, row in enumerate(others, 1):
            conn.execute("UPDATE member SET username=? WHERE id=?",
                         ("%s%d" % (uname, i + 1), row[0]))
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_member_username"
                     " ON member (username) WHERE username!=''")
    except Exception:
        pass                                # 还是有重复就先不建，别为了索引把启动搞挂

    # 「重抽券」以前写的是「抽之后不满意再抽一次」，实现不了（已经发出去的东西
    # 要回滚），改成抽两次取好的，卡面文案跟着改。老库的 item 行是 v1 就写进去的，
    # _seed 不会覆盖，只能在这里补一笔。
    conn.execute("UPDATE item SET desc=? WHERE code='reroll_card' AND desc LIKE '宝箱随机件%'",
                 ("下一箱开出随机件的时候抽两次，取更好的那个。",))


def _migrate_v23(conn):
    """v23：商店缩成两张半价签 + 宝箱明码标价。

    三件事，都要能重复跑：
      1. 木 / 铜 / 银三档定价。以前是「不零售」，因为里面只有券，
         按券数卖确实比单买券贵一点点，但那点差价是「开箱」这件事本身的价格；
         一直挂「不零售」，孩子想给自己的券凑个整就找不到入口。
         价 = 保底券数 × 娱乐券单价，单价从 item 表里读，不写死。
      2. 商店下架：只留好友券和好友过夜卡。其余的券和卡本来就该由打分和开箱
         挣出来，能用星尘直接买的只有这两件（它们要家长掏钱、出时间配合）。
      3. 娱乐券间隔的单位从小时改成分钟 —— 那是设置项，由 _seed 的补差集负责，
         旧 key 收进 RETIRED_SETTINGS，这里不用管。
    """
    fun = conn.execute("SELECT price FROM item WHERE code='ticket_fun'").fetchone()
    per = float(fun[0]) if fun and fun[0] else 7.0
    for tier in (1, 2, 3):
        row = conn.execute("SELECT tickets FROM box_tier WHERE tier=?", (tier,)).fetchone()
        if not row:
            continue
        price = int(round(float(row[0] or 0) * per))
        if price <= 0:
            continue
        conn.execute("UPDATE box_tier SET purchase_price=?, purchase_allowed=1 WHERE tier=?",
                     (price, tier))
    # 完美箱是打到 49 分白拿的，任何情况下都不挂价签
    conn.execute("UPDATE box_tier SET purchase_price=NULL, purchase_allowed=0 WHERE tier=7")

    # v23 当时只留这两件。这一刻的取值写死在函数里，不跟 seed_data 走 ——
    # 迁移是历史，后面每一版都会再改一次，跟着 seed_data 走的话老库会跳到未来状态。
    codes = ["ticket_friend", "friend_stay"]
    q = ",".join("?" * len(codes))
    conn.execute("UPDATE item SET purchasable=1 WHERE code IN (%s)" % q, codes)
    conn.execute("UPDATE item SET purchasable=0 WHERE code NOT IN (%s)" % q, codes)


def _migrate_v24(conn):
    """v24：宝箱保底重排 + 商店换成「六种券 + 三档箱」。

    四件事，逐条幂等：
      1. 补 box_tier.cards_json 列（CREATE TABLE 不会给老库补列）。
      2. 七档保底按 seed_data.BOX_TIERS 重写：券数、星尘（全部清零）、
         保底卡改成有序列表、随机件概率照旧、售卖的只剩金/钻/王。
         数值来自 seed_data 而不是写死在这里：七档是配置，不是历史。
      3. 商店上架六种券，卡全部下架。
      4. 零花钱兑换申请表由 schema.sql 的 CREATE TABLE IF NOT EXISTS 建出来。
    """
    _ensure_column(conn, "box_tier", "cards_json", "TEXT NOT NULL DEFAULT '[]'")

    for t in seed_data.BOX_TIERS:
        tier, _code, _name, thr, tk, sd, rate, cards, dr, price = t
        conn.execute(
            "UPDATE box_tier SET threshold=?, tickets=?, stardust=?, random_rate=?,"
            " cards_json=?, card_rarity=?, card_count=?, diamond_rate=?,"
            " purchase_price=?, purchase_allowed=? WHERE tier=?",
            (thr, tk, sd, rate,
             json.dumps([{"rarity": r, "count": c} for r, c in cards], ensure_ascii=False),
             cards[0][0] if cards else "", sum(c for _, c in cards), dr, price,
             1 if (price and _code in seed_data.SHOP_BOXES) else 0, tier))

    shop = list(seed_data.SHOP_TICKETS)
    q = ",".join("?" * len(shop))
    conn.execute("UPDATE item SET purchasable=1 WHERE category='ticket' AND code IN (%s)" % q, shop)
    conn.execute("UPDATE item SET purchasable=0 WHERE category='ticket' AND code NOT IN (%s)" % q, shop)
    conn.execute("UPDATE item SET purchasable=0 WHERE category='card'")


def _migrate_v25(conn):
    """v25：头像。

    这一版一个新列都没有 —— member.avatar 从 v13 就摆在那儿，但当年存的是
    「P1」「C1」这种占位符（界面那时只是拿它取前两个字当文字头像）。
    现在这一列的含义变了：它存的是 web/avatars/<值>.svg 里的那个文件名。

    所以要把老值过一遍，三种情况：
      · 已经是真头像的文件名   -> 不动
      · 名字能对上「爸爸妈妈女儿儿子」之一 -> 换成对应的那款，一进设置页就有头
      · 其余（含当年那些占位符）-> 清成空串，显示回落成名字首字

    为什么不硬塞一个默认脸给所有人：老库里可能有个「奶奶」，
    给她配 dad_1 还是 mom_1 都是系统在替她决定，而这一列本来就是她能自己挑的。
    空着不是丢数据，是「还没挑过」。

    判合规时按「忽略大小写」比 —— 当年种子里是 "P1" 这种大写值，
    不忽略大小写会把它误判成乱值。但**别把值本身转成小写**：v36 起
    头像清单里是 B01 / D01 这种大写，转小了就成了另一个名字，在 NAS
    （Linux，文件名区分大小写）上会直接找不到图。
    """
    known = set(t.upper() for t in seed_data.AVATAR_TOKENS)
    fixed = cleared = 0
    for r in conn.execute("SELECT id, name, avatar FROM member").fetchall():
        old = str(r["avatar"] or "").strip()
        if old.upper() in known:
            continue
        new = seed_data.AVATAR_BY_NAME.get(str(r["name"] or "").strip(), "")
        if old != new:
            conn.execute("UPDATE member SET avatar=? WHERE id=?", (new, r["id"]))
            if new:
                fixed += 1
            elif old:
                cleared += 1
    if fixed or cleared:
        print("  v25：%d 个成员补上默认头像，%d 个占位值清掉（回落成名字）" % (fixed, cleared))


def _migrate_v29(conn):
    """v29：心愿的「按哪一条提交」。

    只有新增一张表，老库跑过来什么都不动 —— 已经达成的心愿没有 claim
    记录，那正好：它们本来就是在「不用选条件」的年代达成的，回头补一条
    「谁批的」纯属编造。读的一侧把「没有 claim」当成「当年直接点达成的」，
    不猜、不补写。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wish_claim ("
        " id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        " wish_id      INTEGER NOT NULL,"
        " cond_key     TEXT    NOT NULL,"
        " note         TEXT    NOT NULL DEFAULT '',"
        " status       TEXT    NOT NULL DEFAULT 'pending',"
        " created_at   TEXT, created_by INTEGER,"
        " resolved_at  TEXT, resolved_by INTEGER,"
        " reject_note  TEXT    NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_wish_claim ON wish_claim (wish_id, cond_key)")


def _migrate_v26(conn):
    """v26：多选条件（原来的「做到一条就算」）加一格「做到其中几条算成」。

    没有新列，改的是 cond_json 里的内容。v25 存下来的 any 条件只有 items，
    没有 need —— 那时的语义就是「任一条」，等价于 need=1。这里把这一格显式写进去，
    免得库里同一形状的条件有的带这个键、有的不带，读代码的人要分两种情况想。

    只补缺的那一格，不动别的键；已经带 need 的原样留着（幂等）。
    值写坏了的（不是整数、小于 1、比勾的条数还大）也一起夹回合法范围，
    因为读取侧 _any_need 本来就要求 1..条数；让它两边口径一致。
    """
    fixed = 0
    for r in conn.execute("SELECT id, cond_json FROM wish"
                          " WHERE cond_type='any'").fetchall():
        try:
            c = json.loads(r["cond_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(c, dict) or not isinstance(c.get("items"), list):
            continue
        n = len([it for it in c["items"] if isinstance(it, dict)])
        if n <= 0:
            continue
        try:
            k = int(c["need"]) if c.get("need") is not None else 1
        except (TypeError, ValueError):
            k = 1
        k = max(1, min(k, n))
        if c.get("need") == k:
            continue
        c["need"] = k
        conn.execute("UPDATE wish SET cond_json=? WHERE id=?",
                     (json.dumps(c, ensure_ascii=False), r["id"]))
        fixed += 1
    if fixed:
        print("  v26：%d 条多选条件补上「做到几条算成」" % fixed)


def _migrate_v30(conn):
    """v30：家长忘打卡兜底。

    这一版只多一张表：wish_pool_log。它记的是「全家忘打卡」那笔注入的凭据 ——
    哪一天漏了、漏了哪个孩子、注入多少、算不算进度。星尘本身照旧写进
    wish_pool_entry（source='penalty'），池子的进度口径一点没变（还是求和）。

    schema.sql 里已经写了 CREATE IF NOT EXISTS，这里再写一遍是为了那种
    「只还原了旧备份」的场景，迁移链要能自己把表补齐。

    设置项那两半不在这里动：新增的 ticket.weekend_double 与
    task.claim_deadline_hours 由 _seed 的补差集加，删掉的五项由
    RETIRED_SETTINGS 删，两处都幂等，老库跑一遍就齐。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wish_pool_log ("
        " id        INTEGER PRIMARY KEY AUTOINCREMENT,"
        " pool_id   INTEGER,"
        " kind      TEXT    NOT NULL DEFAULT 'penalty',"
        " day       TEXT    NOT NULL,"
        " member_id INTEGER,"
        " kids_json TEXT    NOT NULL DEFAULT '[]',"
        " kids_days INTEGER NOT NULL DEFAULT 0,"
        " stardust  REAL    NOT NULL DEFAULT 0,"
        " counted   INTEGER NOT NULL DEFAULT 1,"
        " note      TEXT    NOT NULL DEFAULT '',"
        " ts        TEXT    NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pool_log_day ON wish_pool_log (kind, day)")


def _migrate_v31(conn):
    """v31：孩子端整套界面换成「糖果冒险」。

    纯前端替换，一行 DDL 也没有 —— 但函数照样挂上链。第 10 节那条
    「加一版就在迁移链上挂一行」的规矩，就是 `_migrate_v29` 没挂逼出来的：
    挂了空函数，「这一版的迁移在哪」永远有确定答案，不用去翻 git 历史。

    改动落在 web/ 下：新增 child.js（孩子端每一屏）、child.css、
    child-tokens.css（孩子端变量）、candy-icons.js（43 个图标的雪碧图）、
    candy/（图标与装饰 SVG）；app.js 删掉旧的七屏孩子端渲染，改成
    按 body.kid 分叉到 child.js。规则、接口、库结构一律没动。
    """
    return


def _migrate_v32(conn):
    """v32：娱乐券的「休息」从每一段改到每一轮。

    以前孩子用 1 张、30 分钟放完就被锁 60 分钟，第二张点不动；实际要的是
    白天连续 3 张、晚间连续 2 张，一轮用满才休息，中间可以一张一张地续。
    引擎那边重写了「轮」的判定，这里只跟着改设置项的说法 —— 几项的意思
    从「单次 / 全天晚间 / 两轮之间」变成了「一轮 / 晚间一轮 / 一轮结束之后」，
    名字不改的话，家长改的时候不知道自己在改什么，复查时也看不出哪句过期了。

    新增的 ticket.renew_within_minutes 不在这里：它由 _seed 的补差集加，
    跟其他新增设置项同一个入口。

    只在还是原来的文案时才换。这两列家长本来也改不到，保守一点没坏处。
    """
    fixes = [
        ("ticket.single_max", "娱乐券单次上限", "单位：张。",
         "娱乐券一轮上限",
         "单位：张。白天一轮最多几张。一轮之内可以一张一张地续，用满这一轮才休息。"),
        ("ticket.cooldown_minutes", "娱乐券间隔", "单位：分钟。两轮之间至少隔这么久。",
         "娱乐券休息时长",
         "单位：分钟。一轮结束（用满，或者超过续费窗口没续）之后要休息这么久。"),
        ("ticket.evening_max", "娱乐券晚间上限", "单位：张。",
         "娱乐券晚间一轮上限",
         "单位：张。晚间开始的那一轮按这个数算，白天开始的仍按白天那个。"
         "一轮算白天还是晚间，由这一轮首张的开始时刻定。"),
    ]
    for key, old_label, old_note, label, note in fixes:
        conn.execute("UPDATE setting SET label=?, note=? WHERE key=? AND label=? AND note=?",
                     (label, note, key, old_label, old_note))


def _migrate_v33(conn):
    """v33：孩子端把「家长直接派下来的任务」重新列出来。空迁移。

    库里没有要改的东西。任务状态一直是两套：大厅里领来的 claimed（在做），
    家长直接派的 pending（待做）。服务端一直把两种都放进「进行中」交给前端，
    是 v31 换孩子端界面时，两处列表写成了只认 claimed，把 pending 整个滤掉。
    于是女儿手上那条派下来的活只有大厅头上一句「你在做 1 件」数着它，
    列表里一条都不剩，连被退回（退回就是回到 pending）都看不出来了。

    修的是前端，所以这里不动库；挂上这个版本号是为了让「孩子端显示哪一版、
    代码改到哪一版」对得上，跟 v31 那次空迁移同一个用法。
    """
    return


def _migrate_v34(conn):
    """v34：给「忘打卡兜底」补上起点。空迁移。

    新增两条设置项：family.start_date（系统起用日，默认建库那天）与
    missed.lookback_days（回看天数，默认 7）。两条都由 _seed 里那段
    「按 key 补差集」自己加进来，这里没有 DDL 要跑。

    老库里已经落下的错误补记与罚款不在这里动手：那要改分数、改星尘、
    还要看有没有连带发出宝箱，属于「看清楚再动」的事。用
    tools/purge_prestart.py（默认只预演）单独清，那个脚本会把清单列全。
    """
    return


def _migrate_v35(conn):
    """v35：家长端换皮「糖果冒险 · 角色换位」。空迁移。

    只动前端：家长端底栏从 6 格收成 5 格（总览 / 审核 / 打分 / 发布 / 我的），
    日志与设置下沉成二级页（日志从总览的「最近发生 · 查看全部」进，设置收进
    「我的」的快捷清单），「任务」改名「发布」。新增 web/parent.css、
    parent-tokens.css、parent-icons.js 与 web/parent/*.svg 四个静态文件。

    库结构、接口形状、设置项一条没变，所以这里没有 DDL 要跑。照 v31（孩子端换皮）
    与 v33（孩子端列表口径）的惯例，换皮也占一个版本号，好让 meta.schema_version
    跟 web/app.js 里「这一版」那句话对得上。
    """
    return


def _migrate_v36(conn):
    """v36：头像换成「糖果冒险」那套 40 张，孩子登录改成「点头像 + 4 位密码」。

    这一版只动两处数据，没有 DDL：
      · 老头像那 12 个 token（dad_1 / mom_2 / girl_3 …）换到新的 40 个里
        同组同序号那一款（girl_1 -> G01、mom_3 -> M03）。就近对应，
        四个人的画风都还是原来那一挂，不会突然变成一张陌生的脸。
      · 新设置项 family.name（登录页那句家庭名）由 _seed 的补差集自己加进来。

    member 表本身不动：孩子的账号名留着（动态日志、家人账号页、审计都要显示），
    只是登录页不再让他输。孩子的密码也不在这里改 —— 迁移里悄悄换凭据是坏习惯，
    以后没人说得清「我的密码怎么变了」。要统一置成 4 位初值走 tools/set_pins.py
    （默认只预演，--apply 才动手）。
    """
    pairs = []
    for i in range(1, 4):
        pairs += [("dad_%d" % i, "D%02d" % i),
                  ("mom_%d" % i, "M%02d" % i),
                  ("boy_%d" % i, "B%02d" % i),
                  ("girl_%d" % i, "G%02d" % i)]
    n = 0
    for old, new in pairs:
        n += conn.execute("UPDATE member SET avatar=? WHERE avatar=?", (new, old)).rowcount or 0
    if n:
        print("  v36：%d 个成员的头像换到新的一套（老 token 按同组同序号对应）" % n)


def _migrate_v37(conn):
    """v37：打分页四态标签、保存行为、25 处二次确认。空迁移。

    三件事都只动前端与判定口径，没有 DDL、也不改存量数据：
      · 打分页那一天站哪一格，从「前端拿 scored / can_edit 自己拼」改成
        后端一处给（engine.score_day_state）。
      · 打过的日子默认只读，点「修改」进编辑态才有取消 / 保存。
      · 会动账的动作点下去先过一层 askSheet 确认。
    外加两条：补记的那天锁死（submit_day 遇 MISSED_NOTE 直接拒），
    以及保存后退回上级 / 页面跳顶两个老毛病。

    挂版本号是为了让 meta.schema_version 跟 web/app.js 里「这一版」那句话
    对得上，跟 v31 / v33 / v35 / v36 那几次空迁移同一个用法。
    """
    return


def _migrate_v38(conn):
    """v38：宝箱拆成「发箱」与「开箱」两步。

    以前周期结算是一次做完的：券、保底卡、随机件在同一秒里全发到孩子账上，
    孩子手上从来没有过一只「待开的箱子」，那 10/20/40/70% 的随机件概率也只
    是后台一次静默抽奖。这一版起结算只落一只待开箱，箱子里有什么压到他
    点开那一刻才抽；直购仍然是付完星尘当场开（配同一段开箱动画）。
    一直没开的箱，下个周期结算时系统替他开掉（engine.auto_open_stale）。

    DDL 只有一列：box_open.opened_at。NULL = 待开，有值 = 开过了。
    存量记录一律按 ts 补上 —— 那些箱子里的东西在 v38 之前就已经发到手上，
    不补的话孩子登录会看到一堆历史待开箱，点开还会再发一遍。

    随机件池跟着 seed_data 重写一遍（照 v24 的做法：七档是配置，不是历史）：
    钻石箱那件「普通卡 2 张」改成自选，金箱那件 label 里「可在家长侧指定
    替换」的半截承诺一并去掉 —— 全项目从来没有过那个入口。
    """
    if _ensure_column(conn, "box_open", "opened_at", "TEXT"):
        conn.execute("UPDATE box_open SET opened_at=ts")
        print("  v38：存量开箱记录按 ts 标成已开（不会变成待开箱重复发货）")

    for t in seed_data.BOX_TIERS:
        pool = seed_data.BOX_RANDOM_POOL.get(t[1], [])
        conn.execute("UPDATE box_tier SET random_pool=? WHERE tier=?",
                     (json.dumps(pool, ensure_ascii=False), t[0]))


def _migrate_v39(conn):
    """v39：孩子端首页与宝箱页照设计稿重排。空迁移。

    两屏都只动前端，没有 DDL、也不改存量数据：
      · 首页撤掉「本周能量」卡 —— 宝箱页头一行报的就是同一个数，摆两处
        孩子会看到同一根进度条各说各话；换上一张「这一周的七分」，
        七行维度 × 七列这一周，结论那两句是现算的，不落库。
      · 宝箱页状态行分「还锁着 / 可以开啦 / 本周已领」三种，七档从
        「一条横阶梯 ＋ 卡下七行明细」并成七列，随机件概率收进卡尾一句。
    后端只多给一份数据：`/api/score/cycle` 每天带上七个维度的 0/1，
    外加一份行定义（今天这套维度），七分矩阵直接吃，界面不再自己拼。

    挂版本号是为了让 meta.schema_version 跟 web/app.js 里「这一版」那句话
    对得上，跟 v31 / v33 / v35 / v36 / v37 / v39 那几次空迁移同一个用法。
    """
    return


def _migrate_v40(conn):
    """v40：宝箱七档换成各自的图。

    以前 seed_data.BOX_ICONS 里六档共用一张 rw_box、第七档 rw_box_open：
    家长在设置「给它们换张图」里看到的七档宝箱是同一只棕色箱子，
    跟孩子端宝箱页那七只（木/铜/银/金/钻/王/完满，各一个颜色）完全对不上。

    现在按 tier 配到 bx_wood … bx_perfect，配色照抄 web/candy/i-chest-*.svg。
    只动「还是旧默认图」的那几行：家长自己挑过的（哪怕挑的还是 rw_box
    这一只）一律不碰 —— 判据就是那两个旧 token，老库里没改过的写法
    只可能是它们。
    """
    for tier, tok in sorted(seed_data.BOX_ICONS.items()):
        conn.execute(
            "UPDATE box_tier SET icon=? WHERE tier=? AND icon IN ('rw_box','rw_box_open')",
            (tok, tier),
        )


def _migrate_v41(conn):
    """v41：活力这一项统一成「吃饭」口径。只改一句话，没有 DDL。

    历史资料（原始规则、打分表、游戏化设计 v2、规则全书 v10~v29）里
    「活力」从头到尾都是吃饭表现；`seed_data` 里那句「运动、户外、精力释放」
    是后来写歪的，家长端设计稿照着它也写成了运动。WW先生 2026-09-23 拍板：
    活力 = 吃饭的表现，所有端统一这个口径。

    meaning 家长改不了（设置页只能改名和换图），所以存量库里那句老话
    只能靠这一次迁移换掉。判据带上老文案全文：万一哪家自己动过库，
    不在这句话上的就不动。
    """
    conn.execute(
        "UPDATE dimension SET meaning=? WHERE code='vigor' "
        "AND meaning IN ('运动、户外、精力释放', '运动、户外，精力释放')",
        ("好好吃饭，把身体养得结实",),
    )


def _migrate_v42(conn):
    """v42：券的「办好了没」与「玩完了收没收」。

    两件以前账上不记的事：

    1. 不带时长的券（陪伴 / 选择 / 豁免 / 独处 / 好友）批了只是家长答应了，
       还要真的去办。以前扣完券这条就没了下文，孩子那边看到「可以用啦」
       然后一直等一个不会自己发生的时刻，家长处理完待办也就忘了。
       现在批了进 fulfill_status='waiting'，家长点「办好了」并写一句才算完。

    2. 带时长的券玩完了从屏幕上直接蒸发，孩子不知道那一轮结束没有。
       现在留一张存档卡，他点过「知道了」（ack_at）才收进「今天用过什么」。

    存量数据一律不补：老库里那些早就过完的券，凭空冒出来会变成一串
    「等爸爸妈妈办」的旧账，家长一看就是十几件。只有新批的才进这两条链。
    """
    _ensure_column(conn, "ticket_request", "fulfill_status", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "ticket_request", "fulfill_note", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "ticket_request", "fulfilled_at", "TEXT")
    _ensure_column(conn, "ticket_request", "fulfilled_by", "INTEGER")
    _ensure_column(conn, "ticket_request", "remind_at", "TEXT")
    _ensure_column(conn, "ticket_request", "ack_at", "TEXT")


def _migrate_v43(conn):
    """v43：国家法定节假日日历。

    新增 calendar_day 表（DDL 在 schema.sql 里，init_db 会自动建），
    用来回答「这天放不放假」。跟 holiday 表是两件事，别合并：holiday
    是家长手填的区间，带着「假期版维度名」和「首尾过渡日不计分」；
    calendar_day 是从公开数据源拉回来的国家日历，只回答放不放假。

    判定链（engine.is_off_day）：家长填的假期 → 国家日历说放假 →
    国家日历说调休上班（不放假）→ 周六周日。券面值翻倍和硬停止
    两处共用它。以前只认最后一条，所以调休上班的周末两头都错。

    存量库不用补任何数据：表是空的，第一次同步会把今年和明年拉回来；
    在那之前判定退回老行为（只看周末），不会突然把哪天判错。

    另有两处设置项的显示名和说明跟着换口径：判定不再是「周末」，是
    「不用上学的日子」。seed_data 里改了只管新建的库，存量库里还是老话，
    留着就是同一件事两套说法。判据带上老文案 —— 哪家自己改过显示名的，
    不在这句话上的就不动。
    """
    conn.execute(
        "UPDATE setting SET label=?, note=? WHERE key='ticket.weekend_double'"
        " AND label='周末快乐翻倍'",
        ("放假的日子翻倍",
         "默认关。打开后「不用上学的日子」娱乐券面值翻倍（30 分钟变 60）：周末、"
         "国家法定假日、家长在假期日历里填的寒暑假都算；调休上班的那个周末不算，"
         "那天翻倍不生效。只放大兑换时长，券的张数、有效期、其他券一律不动。"))
    conn.execute(
        "UPDATE setting SET label=?, note=? WHERE key='ticket.curfew_weekend'"
        " AND label='硬停止（周末与假期）'",
        ("硬停止（不用上学的日子）",
         "周末、国家法定假日、家长填的寒暑假用这个，可以比上学日放宽一点。"
         "调休上班的周末按上学日算，那天要上学。"))


if __name__ == "__main__":
    init_db(verbose=True)
    print("数据库就绪:", DB_PATH)