# -*- coding: utf-8 -*-
"""造一份「过了一周」的演示数据，用来看界面、跑巡检。

不碰 data/family.db：整个脚本把 FAMILY_DATA_DIR 指到 data/demo，
建一个单独的库，灌完就退出。想重来直接删 data/demo 再跑一次。

    python tools/demo_seed.py
    FAMILY_PORT=8090 FAMILY_DATA_DIR=data/demo python server.py
"""
import os
import random
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

DEMO_DIR = os.path.join(APP, "data", "demo")
os.environ["FAMILY_DATA_DIR"] = DEMO_DIR
os.environ["FAMILY_DB"] = os.path.join(DEMO_DIR, "family.db")

if os.path.exists(os.environ["FAMILY_DB"]):
    if "--force" not in sys.argv:
        print("已有演示库：%s" % os.environ["FAMILY_DB"])
        print("想重建就加 --force（会把这个库连 -wal/-shm 一起删掉重建）。")
        sys.exit(0)
    # --force 要真的重建。以前它只是「不退出」，旧数据还堆在库里，
    # 跑第二次就撞上「本周任务星尘已达上限」，脚本当场报错退出。
    # 这里不删文件（有些环境下删不掉），改成把表全清掉，效果一样。
    import sqlite3
    _con = sqlite3.connect(os.environ["FAMILY_DB"])
    for _n in [r[0] for r in
               _con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                            " AND name NOT LIKE 'sqlite_%'")]:
        _con.execute("DROP TABLE IF EXISTS [%s]" % _n)
    _con.commit()
    _con.close()
    print("  --force：旧表已清空，重建")

import db            # noqa: E402
import engine as E   # noqa: E402

random.seed(20260917)

# 演示库的登录密码。正式库不走这里 —— 那边留给本人第一次打开时自己设，
# 系统不该替全家人定一个统一密码。这里固定下来是为了人工验和 e2e 能写死。
#
# v36 起孩子不算「账号」了：他的入口是登录页那面头像墙 —— 点自己那张，按 4 位
# 数字。所以两个孩子的密码必须是 4 位数字。家长那条还是账号 + 密码。
#
# 四个人统一用 1234，是 WW 先生点名要的：装完先保证一家人都能进去，
# 之后由他自己在系统里一个一个改掉。演示库跟着走同一套，e2e 才好写死。
# 「进来的是不是本人」这条不靠密码不同来验 —— e2e 在每次登录之后
# 拿 /api/bootstrap 的 me.name 对了一遍，密码一样一样能查出来接错线。
DEMO_PW = {"爸爸": "1234", "妈妈": "1234", "女儿": "1234", "儿子": "1234"}


def seed_accounts():
    """把演示库的账号密码补齐，并把管理员指给第一个家长。"""
    from api.auth import hash_password
    for m in db.query("SELECT * FROM member WHERE active=1 ORDER BY sort, id"):
        pw = DEMO_PW.get(m["name"], "0000")
        db.execute("UPDATE member SET username=?, password_hash=? WHERE id=?",
                   (m["username"] or m["name"], hash_password(pw), m["id"]))
    dad = db.query_one(
        "SELECT id FROM member WHERE role='parent' AND active=1 ORDER BY sort, id LIMIT 1")
    if dad:
        db.execute("UPDATE member SET is_admin=0")
        db.execute("UPDATE member SET is_admin=1 WHERE id=?", (dad["id"],))
    print("  演示账号：" + "　".join("%s/%s" % (k, v) for k, v in DEMO_PW.items())
          + "　管理员＝爸爸")


def main():
    db.init_db(verbose=True)
    seed_accounts()
    kids = db.query("SELECT * FROM member WHERE role='child' ORDER BY sort")
    dad = db.query_one("SELECT * FROM member WHERE role='parent' ORDER BY sort")
    if not kids:
        print("库里没有孩子账号")
        return

    def must(r, what):
        """引擎里大多数函数出错时返回 {'ok': False, 'msg': ...} 而不是抛异常。

        演示脚本照着 happy path 一路往下写，中间有一次 anticipation 没对上
        （比如并发心愿已经满 2 个），后面就崩在一个 KeyError 上，
        报错的位置离真正的原因隔着十几行。这里统一拦一道。
        """
        if not isinstance(r, dict) or not r.get("ok"):
            raise SystemExit("演示数据造不下去 —— %s：%s"
                             % (what, (r or {}).get("msg") or r))
        return r

    dims = [d["code"] for d in E.dimensions(E.day_mode(E.today()))]
    today = E.today()

    # 补分有窗口限制（默认只能补最近 2 天）。演示库要一整周的历史，
    # 所以先把窗口放开，灌完再放回去，免得设置页里躺着一个奇怪的数。
    old_win = db.query_one("SELECT value FROM setting WHERE key='score.backfill_days'")
    db.execute("UPDATE setting SET value='30' WHERE key='score.backfill_days'")
    db.settings_all(force=True)          # db.cfg 有缓存，改完得让它失效

    # 1) 把最近 14 天补上分数，会自然带出「上一个周期已结算 + 本周进行中」。
    #    女儿几乎满分，儿子常缺项，这样两边的宝箱档位明显不一样。
    #    儿子那串里那个 7（下标 3）是他「一项都没做到」的一天。月历上
    #    「打了分但 0 分」和「压根没打分」是两种底色，演示库必须各留一个，
    #    否则看的人只会看到绿色和黄色，分不出这两种。
    plan = {"女儿": [0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0],
            "儿子": [2, 1, 4, 7, 3, 1, 5, 2, 4, 1, 3, 2, 6, 2]}
    for i in range(14, 0, -1):
        day = E.fmt(E.parse_day(today) - timedelta(days=i))
        for k in kids:
            miss = plan.get(k["name"], [1] * 14)[14 - i]
            undone = random.sample(dims, min(miss, len(dims)))
            r = E.submit_day(k["id"], day, undone, operator_id=dad["id"])
            if not r.get("ok"):
                print("  打分跳过 %s %s: %s" % (k["name"], day, r.get("msg")))

    # 2) 补几个星探时刻，家长端和孩子端都看得到
    #    v28：每一条挂到具体哪一项上。孩子端的「分数」页是按维度看的 —
    #    星星时刻不挂维度，那一页就只剩「哪项没拿到」，看不出「哪项被夸过」。
    moments = [
        ("今天自己把书包收好了，还说了一句「明天我自己记得」", "stardust", 5, "order"),
        ("练琴半小时没催，自己主动坐下开始", "both", 3, "study"),
        ("弟弟把水洒了，他先拿抹布去擦，没抱怨", "energy", 1, "bond"),
        ("主动把阳台的花浇了，还数了数新开了几朵", "stardust", 5, "craft"),
    ]
    for k in kids:
        for j, (phrase, kind, _, dim) in enumerate(moments):
            E.add_explore(k["id"], E.fmt(E.parse_day(today) - timedelta(days=8 - j)),
                          phrase, kind=kind, dimension_code=dim, operator_id=dad["id"])

    # 3) 只结算已经过完的周期。本周还在进行中，得留着給「这周」页看进度。
    past = db.query("SELECT * FROM cycle WHERE status='open' AND end_date<?"
                    " ORDER BY start_date", (today,))
    for c in past:
        r = E.settle_cycle(c["id"], operator_id=dad["id"])
        print("  结算周期 member=%s start=%s: %s"
              % (c["member_id"], c["start_date"], r.get("msg") or "ok"))

    # 3.5) v38：结算只把箱子发下来，箱子里有什么要点开才知道。
    #      演示库把一周的历史压在同一秒里造出来，前面那几个周期发下来的箱子
    #      ts 会全撞在同一刻 —— auto_open_stale 是按 ts 判「陈箱」的，那就一只
    #      都判不出来。先把箱子时间挪回它自己那个周期，再照 ③ 走一遍：
    #      当前周期之前的箱子，真实系统里在「下一次结算」时已经替孩子开掉了。
    db.execute("UPDATE box_open SET ts = COALESCE((SELECT c.end_date || ' 20:00:00'"
               " FROM cycle c WHERE c.id = box_open.cycle_id), ts)")
    for k in kids:
        cur = E.current_cycle(k["id"])
        if cur:
            done = E.auto_open_stale(k["id"], before_day=cur["start_date"],
                                     operator_id=dad["id"])
            if done:
                print("  陈箱替开 member=%s: %d 只" % (k["id"], len(done)))
    # 开箱那一刻挪回箱子时间，跟 ts 对齐 —— 不然「最近开出来的」会显示成建库时刻
    db.execute("UPDATE box_open SET opened_at = ts WHERE opened_at IS NOT NULL")

    db.execute("UPDATE setting SET value=? WHERE key='score.backfill_days'",
               (old_win["value"] if old_win else "2",))
    db.settings_all(force=True)

    # 4) 花一点钱：买券、买卡、开个箱子，让「我的」和流水有东西
    for k in kids:
        E.buy_ticket(k["id"], "ticket_fun", 2, operator_id=dad["id"])
        E.buy_card(k["id"], "card_priority", operator_id=dad["id"])
    # v38 起宝箱是「发下来先躺着、孩子自己点开」。演示库要两种都留着：
    #   第一只不点开 —— 宝箱页顶部那张「点我打开」的提醒卡得有东西挂；
    #   其余当场开掉 —— 「最近开出来的」那一段不能是空的。
    if kids:
        made = E.issue_box(kids[0]["id"], 3, source="free", operator_id=dad["id"])
        if made and made.get("ok"):
            print("  待开箱（不点开）: member=%s box=%s" % (kids[0]["id"], made["box_id"]))
    for k in kids[1:]:
        made = E.issue_box(k["id"], 4, source="free", operator_id=dad["id"])
        if made and made.get("ok"):
            E.open_box(k["id"], made["box_id"], operator_id=dad["id"])

    # 5) 待做 / 待确认 / 已确认三种各一条。
    #    「待做」这条是家长直接派下去、孩子还没交的（pending）。它跟大厅领来的
    #    （claimed）是两回事，孩子端两处过滤都只认后一种，于是这条被整个藏掉：
    #    「全部 1 件」底下写着「手上没有活」。演示库必须留着这一条，
    #    否则 e2e 里没有任何东西能证明它看得见。
    t0 = E.create_task(kids[0]["id"], "给弟弟读一本绘本", "读完一整本，合上书问他三个问题",
                       reward_type="energy", reward={"amount": 1}, created_by=dad["id"])
    print("  待做的任务（家长直接派的）: %s" % t0)
    t1 = E.create_task(kids[0]["id"], "整理书架", "三层都归位，家长只看结果不动手",
                       reward_type="stardust", reward={"amount": 10}, created_by=dad["id"])
    E.submit_task(t1, kids[0]["id"])
    t2 = E.create_task(kids[0]["id"], "擦一遍阳台栏杆", "没有浮灰，抹布洗过再收",
                       reward_type="energy", reward={"amount": 2}, created_by=dad["id"])
    E.submit_task(t2, kids[0]["id"])
    E.confirm_task(t2, operator_id=dad["id"])

    # 6) 校准一条，会自己挂一条修复任务
    r = E.add_calibration(kids[1]["id"], 3, "说好 8 点回家，9 点半才回",
                          effect_type="task", template="apology", operator_id=dad["id"])
    print("  校准: %s" % r.get("msg", "ok"))

    # 7) 心愿单三个动作全摆出来：孩子许愿 → 家长定条件 → 达成兑现。
    #    这一版新加的「挂起」状态必须有一条，否则界面上那个「等爸爸妈妈定条件」
    #    的分区和进度条都看不见。四条覆盖挂起 / 进行中两种条件 / 已达成。
    must(E.wish_one(kids[0]["id"], "想要一套 48 色彩铅",
                    reward_desc="画完那本速写本就用得上",
                    operator_id=kids[0]["id"]), "孩子许愿")            # 挂起，等家长定条件
    must(E.create_wish(kids[0]["id"], "想去一次天文馆", "task_count", {"value": 3},
                       "陪她去一次", "", 0, operator_id=dad["id"]), "天文馆")   # 进行中，靠交任务
    must(E.create_wish(kids[1]["id"], "想换那个新卡册", "stardust", {"value": 150},
                       "旧的塞不下了", "自己出一半", 0, operator_id=dad["id"]), "新卡册")  # 靠星尘
    wbuf = must(E.create_wish(kids[1]["id"], "周末去吃一次自助", "fixed", {"value": 21},
                              "说好了这周去", "", 0, operator_id=dad["id"]), "自助餐")
    must(E.update_wish_status(wbuf["wish_id"], "achieved", operator_id=dad["id"]), "心愿兑现")
    print("  心愿：挂起 1 / 进行中 2 / 已达成 1")

    # 11) 历史心愿（v18）：结束的心愿也留在墙上，还得看得出是怎么结束的。
    #     一条是还挂着的时候被家长驳回，一条是孩子自己放弃的 ——
    #     这两件事在界面上是两句话（「被驳回」和「自己放弃」），
    #     只造一条，历史里那两种标签就分不出来。
    wb1 = must(E.wish_one(kids[0]["id"], "把房间刷成蓝色",
                          reward_desc="暑假自己刷，不用别人搭手", operator_id=kids[0]["id"]),
               "被驳回的那条")
    must(E.update_wish_status(wb1["wish_id"], "cancelled", operator_id=dad["id"]), "驳回")
    wb2 = must(E.create_wish(kids[1]["id"], "买一整套卡牌收纳盒", "stardust", {"value": 80},
                             "抽屉里塞不下了", "", 0, operator_id=dad["id"]), "收纳盒")
    must(E.update_wish_status(wb2["wish_id"], "cancelled", operator_id=kids[1]["id"]), "自己放弃")
    print("  历史心愿：被驳回 1 / 自己放弃 1")

    # 12) v25 起心愿多了两种条件，v26 把「多选条件」放开到六条都能勾，还多一格
    #     「做到其中几条算成」。不留的话，这几样在演示库里都看不见：
    #       · 女儿那条多选，勾了四条（固定分 / 任务数 / 星尘自付 / 自己写一条），
    #         要凑够两条。孩子端能看到主条按「做到几条」走、每条各列一行、
    #         里面那条自定义标着「靠人判」、星尘那条给他一个「付掉」按钮。
    #       · 儿子那条自己写的，验证「系统算不了」的那种渲染（没有进度条）。
    #     放在这一段之后建，是因为前面那几条会占掉「同时进行中最多 2 个」的名额，
    #     名额是给孩子算的，不是给演示数据算的，撞上了就该让路。
    w_multi = must(E.create_wish(kids[0]["id"], "这周多选达成一个", "any",
                       {"need": 2,
                        "items": [{"type": "fixed", "value": 49},
                                  {"type": "task_count", "value": 4},
                                  {"type": "stardust", "value": 30},
                                  {"type": "custom", "text": "把书桌自己收拾干净"}]},
                       "四条里做到两条就算", "", 0, operator_id=dad["id"]), "多选条件")
    # 名额放宽到 3：v29 要同时摆出「还没交 / 等确认 / 已确认」三种状态，
    # 两个名额放不下三条心愿，而演示库的价值就在于一眼看全。
    # 写进库还不够：db.cfg 有缓存，不刷新的话读回的还是旧上限
    db.execute("UPDATE setting SET value='3' WHERE key='wish.max_active'")
    db.settings_all(force=True)
    must(E.create_wish(kids[0]["id"], "把阳台那几盆花浇完", "any",
                       {"need": 2,
                        "items": [{"type": "task_count", "value": 2},
                                  {"type": "custom", "text": "自己把阳台的花浇一遍，顺便数数开了几朵"}]},
                       "两条都得做到", "", 0, operator_id=dad["id"]), "待提交的心愿")
    w_custom = must(E.create_wish(kids[1]["id"], "把《夏洛的网》读完", "custom",
                       {"text": "读完整本，讲给我听一遍"},
                       "读完讲给我听", "", 0, operator_id=dad["id"]), "自定义条件")
    print("  心愿新条件：多选条件 1（四条里凑两条，含星尘）/ 自己写一条 1")

    E.create_pool("一次露营", "在山上过一夜，帐篷和睡袋家里有", 400, operator_id=dad["id"])
    E.request_overtime(kids[1]["id"], today, 30, "周末的电影还有 30 分钟没看完")
    E.request_help(kids[1]["id"], "数学练习册第 12 页第二题不会", day=today,
                   operator_id=kids[1]["id"])

    # 8) 再补一笔星尘，让两个人的等级拉开一点
    bonus = {"女儿": 220, "儿子": 90}
    for k in kids:
        E.add_ledger(k["id"], "adjust", stardust=bonus.get(k["name"], 120),
                     note="演示数据", operator_id=dad["id"])

    # 9) 留一条待处理的券核销申请。家长端「审核」页和孩子端「我的」页
    #    各有一条真实记录可看，而不是一片空状态。
    #    时钟钉在傍晚 18:00：券的三道时段闸门（间隔 / 晚间 / 硬停止）都看时刻，
    #    不钉的话，这份演示数据在晚上十点之后灌出来就少了这条待办。
    E.freeze_clock(today + " 18:00:00")
    E.submit_day(kids[0]["id"], today, [], operator_id=dad["id"])   # 前置：当天学习任务已完成
    r = E.request_ticket(kids[0]["id"], E.item_by_code("ticket_fun")["id"], 1, note="看一集动画")
    E.freeze_clock(None)
    #    申请 20 分钟不理就自动作废（这是规则本身在起作用，不是 bug）。
    #    但演示库是个静态快照，不是活的：作废之后审核页就空成一片，
    #    没人看得到这一版新加的东西。所以把这条的有效期拉长。
    if r.get("request_id"):
        db.execute("UPDATE ticket_request SET expire_at=? WHERE id=?",
                   ((E.parse_day(today) + timedelta(days=30)).strftime("%Y-%m-%d") + " 23:59:59",
                    r["request_id"]))
    print("  券核销待办: %s" % r.get("msg", "ok"))

    # 9c) 一条「正在玩」的记录（v27）。演示库是个静态快照，翻页面的时候
    #     未必正好有人在使用券，所以这里单开一条，拿**真实此刻**当锚点：
    #     这一刻往前 8 分钟开始、往后 22 分钟结束。灌完数据随手打开页面，
    #     就能看到那条倒计时在走，而不是一块永远空着的「正在玩」。
    #     不拿上面那条待办改：那条要留着演「等你点头」。
    _rn = datetime.now()
    _rs = (_rn - timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S")
    _re = (_rn + timedelta(minutes=22)).strftime("%Y-%m-%d %H:%M:%S")
    #     审批人写进去：v29 起这块和日志都要显示「谁同意的」，
    #     全库只有一位家长动手的话，那一列写谁都一样，等于看不出它有什么用。
    mom = db.query_one("SELECT * FROM member WHERE role='parent' AND id<>?"
                       " ORDER BY sort, id", (dad["id"],)) or dad
    db.execute(
        "INSERT INTO ticket_request (member_id,item_id,qty,day,minutes,status,gate,note,ts,"
        "start_at,end_at,resolved_at,operator_id) VALUES (?,?,1,?,30,'approved','{}',?,?,?,?,?,?)",
        (kids[0]["id"], E.item_by_code("ticket_fun")["id"], today, "看一集动画",
         _rs, _rs, _re, _rs, mom["id"]))
    print("  正在玩: %s → %s（%s 同意的）" % (_rs[11:16], _re[11:16], mom["name"]))

    # 9d) 两条挂在维度上的校准（v28）。孩子端「分数」页要能说出「哪一项被扣过」，
    #     而校准不挂维度的时候，那一页只能显示一个「被扣过 N 次」的总数，
    #     点不出是哪一项。两笔各占一种扣法：扣分钟（秩序）、扣星尘（洁净）。
    E.add_calibration(kids[0]["id"], 2, "桌面两天没收拾，书本摊了一桌",
                      dimension_code="order", effect_type="ticket_min", amount=15,
                      operator_id=dad["id"])
    E.add_calibration(kids[0]["id"], 3, "说好睡前刷牙，昨天和今天都没刷",
                      dimension_code="clean", effect_type="fine", operator_id=dad["id"])
    print("  校准：秩序（扣 15 分钟）/ 洁净（扣星尘）")

    # 9e) v29 三件在界面上非有数据不可看的事：
    #     ① 孩子自己按的那些按钮，日志里写的是他自己的名字（不是「家长」）；
    #     ② 心愿按一条一条提交 —— 女儿那条已确认（妈妈点的），
    #        儿子那条先被驳回、后来又交了一次，正等家长点头；
    #     ③ 券批了之后，首页第一屏那块进度条上写着是谁同意的。
    #
    #     ② 里「驳回过一次又交了第二次」是刻意留的：只看最新那条的话，
    #     上一次为什么没过就消失了，而那句话正是他接着改下去的依据。
    must(E.buy_ticket(kids[0]["id"], "ticket_fun", 1, operator_id=kids[0]["id"]),
         "孩子自己买券")

    _c1 = E.submit_wish_cond(w_multi["wish_id"], "custom",
                             "书桌收干净了，抽屉也理了一遍", operator_id=kids[0]["id"])
    if _c1.get("ok"):
        E.resolve_wish_claim(_c1["claim_id"], True, operator_id=mom["id"])
    _c2 = E.submit_wish_cond(w_custom["wish_id"], "custom",
                             "读完了，我讲给你听", operator_id=kids[1]["id"])
    if _c2.get("ok"):
        E.resolve_wish_claim(_c2["claim_id"], False, operator_id=dad["id"],
                             reject_note="只读到第六章，后面的还没看")
    _c3 = E.submit_wish_cond(w_custom["wish_id"], "custom",
                             "这次从第七章读到最后一章了", operator_id=kids[1]["id"])
    print("  心愿提交：女儿那条 %s 已确认 / 儿子那条驳回过一次，现在等确认"
          % ("是" if _c1.get("ok") else "没"))

    # 9b) 零花钱兑换（v24）。审核页上「等你点头」和「已发放等确认」是两栏，
    #     两栏都得有东西，否则那两块看起来像没做出来。
    must(E.request_cash(kids[0]["id"], 20, note="想买个新笔袋", operator_id=kids[0]["id"]),
         "兑换申请待审")
    q = must(E.request_cash(kids[1]["id"], 10, note="攒着买卡册", operator_id=kids[1]["id"]),
             "兑换申请第二条")
    must(E.resolve_cash_request(q["request_id"], True, operator_id=dad["id"]), "家长同意发放")
    print("  零花钱兑换：待审 1 / 已发放等确认 1")

    # 10) 任务大厅：三种状态各留一条，界面上一眼能看全
    #     先到先得 + 已被人领走（家长撤不掉，孩子端能看到「我在做的」）
    h1 = E.create_task(None, "擦一次全家地板", "客厅加两个房间都擦过，看不见灰",
                       reward_type="stardust", reward={"amount": 8}, created_by=dad["id"], slots=1)
    r1 = E.task_claim(h1, kids[1]["id"])
    print("  大厅先到先得: %s" % r1.get("ok"))
    # 每人一份 + 一个人交了、一个人还在做
    h2 = E.create_task(None, "整理自己的书桌", "桌面清空，书按大小码好",
                       reward_type="stardust", reward={"amount": 3}, created_by=dad["id"], slots=0)
    r2 = E.task_claim(h2, kids[0]["id"])
    r3 = E.task_claim(h2, kids[1]["id"])
    if r2.get("ok"):
        E.submit_task(r2["task_id"], kids[0]["id"])
    # 没人动过的一条，家长可以直接撤
    h3 = E.create_task(None, "把门口的鞋摆整齐", "鞋头朝外，一双一双靠紧",
                       reward_type="ticket", reward={"code": "ticket_fun", "qty": 1},
                       created_by=dad["id"], slots=1)
    print("  大厅任务：先到先得 %s / 每人一份 %s / 没人领 %s" % (h1, h2, h3))

    # 12) 任务记录。孩子端任务页底部摆「最近 3 条 + 展开全部」，回溯近一个月。
    #     演示库原来只有今天那三条，展开按钮永远不出现 —— 一个数据一少就看不见的
    #     功能，靠演示库是验不出来的，e2e 里那句「点一下展开」也就没法写。
    #     这里按天往回造三周：做成的、被退回的、自己放下的各来几条。
    #
    #     时钟必须钉回过去。不钉的话 confirmed_at 全是「现在」，七条挤在同一秒，
    #     「按最后动过的时刻倒序」这条规则在演示库上等同于没有。
    #     星尘给得都小（2 至 5），是怕撞上「一周任务星尘合计 ≤20」那道护栏；
    #     日期也刻意摊在四个自然周里。
    def mk(assignee, title, std, reward_type, reward):
        tid = E.create_task(assignee, title, std, reward_type=reward_type,
                            reward=reward, created_by=dad["id"])
        if not isinstance(tid, int):
            raise SystemExit("演示数据造不下去 —— 发任务「%s」：%s"
                             % (title, (tid or {}).get("msg") or tid))
        return tid

    # (几天前, 标题, 完成标准, 星尘, 结局)
    hist = [
        (3,  "给金鱼换水",       "换掉三分之二，缸壁擦一圈", 3, "confirmed"),
        (5,  "自己洗袜子",       "搓到水清，晾在阳台",       3, "confirmed"),
        (8,  "抄写生字一遍",     "一页，写在田字格里",       5, "returned"),
        (11, "把自己的被子叠好", "铺平对折，枕头摆正",       2, "confirmed"),
        (14, "陪弟弟搭一次积木", "搭完一起收进箱子",         4, "confirmed"),
        (18, "浇一周的花",       "隔天一次，别浇到叶子上",   3, "abandoned"),
        (22, "收拾自己的零食袋", "桌上不留袋子",             2, "confirmed"),
    ]
    tally = {"confirmed": 0, "returned": 0, "abandoned": 0}
    base = E.parse_day(E.today())
    # 造这段要临时把「一周任务星尘 ≤20」那道护栏放到底。
    # 那条检查的条件是 created_at >= 当前周期起始日，没有上界：时钟一钉到过去，
    # 今天造的那些任务也照样算进那一周，三次就顶到 20 了。这是造历史数据独有的
    # 现象（真实使用里任务只会在「现在」发出来）。造完立刻改回去。
    old_cap = db.query_one(
        "SELECT value FROM setting WHERE key='task.stardust_weekly_cap'")
    db.execute("UPDATE setting SET value='999' WHERE key='task.stardust_weekly_cap'")
    db.settings_all(force=True)
    for back, title, std, stardust, end in hist:
        E.freeze_clock(E.fmt(base.fromordinal(base.toordinal() - back)) + " 17:30:00")
        if end == "abandoned":
            # 「不做了」只认大厅领来的那份（引擎里 task_abandon 卡 status='claimed'），
            # 所以这一条必须先挂大厅、再领、再放下 —— 家长直接派下去的活推不掉。
            tid = mk(None, title, std, "stardust", {"amount": stardust})
            # 领的时候引擎会另开一行「他的那一份」，hall_id 指向大厅那条。
            # 后面放下、提交都得用新开那行的 id —— 用大厅那条的 id 会被
            # 「这不是你的任务」挡回来。
            tid = must(E.task_claim(tid, kids[0]["id"]), title + " 领")["task_id"]
        else:
            tid = mk(kids[0]["id"], title, std, "stardust", {"amount": stardust})
            must(E.submit_task(tid, kids[0]["id"]), title + " 交")
        if end == "confirmed":
            must(E.confirm_task(tid, operator_id=dad["id"]), title + " 确认")
        elif end == "returned":
            must(E.return_task(tid, operator_id=dad["id"],
                               note="字写歪了，重写一遍再交"), title + " 退回")
        else:
            must(E.task_abandon(tid, kids[0]["id"]), title + " 放下")
        tally[end] += 1
    E.freeze_clock(None)
    db.execute("UPDATE setting SET value=? WHERE key='task.stardust_weekly_cap'",
               (old_cap["value"] if old_cap else "20",))
    db.settings_all(force=True)
    print("  任务记录：做成 %d / 被退回 %d / 自己放下 %d（摊在近三周，共 %d 条）"
          % (tally["confirmed"], tally["returned"], tally["abandoned"], len(hist)))

    print("")
    for k in kids:
        lv = E.level_of(k["id"])
        snap = E.cycle_snapshot(E.current_cycle(k["id"])["id"])
        print("  %s：周能量 %s，星尘 %s，LV %s %s，券 %s 张"
              % (k["name"], snap["energy"], E.stardust_balance(k["id"]),
                 lv["level"], lv["title"], len(E.to_ticket_list(k["id"]))))
    print("")
    print("演示库建好了：%s" % os.environ["FAMILY_DB"])
    print("起服务：FAMILY_PORT=8090 FAMILY_DATA_DIR=data/demo python server.py")


if __name__ == "__main__":
    main()
