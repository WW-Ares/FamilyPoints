# -*- coding: utf-8 -*-
"""把孩子的登录密码统一改成 1234（4 位数字），方便交接时先能进去，之后再各改各的。

v36 起孩子不算「账号」了：他的入口是登录页那面头像墙 —— 点自己那张，按 4 位
数字。所以这个脚本改的是**孩子的密码**，不是账号名。家长不在这份名单里，
他们的账号密码是本人第一次打开时自己设的，不该被脚本统一掉。

**默认只预演**，把每个人现在是「有密码 / 没密码」、会改成什么打一遍，
一个字都不改。看清楚了再加 --apply。

用法：

    python tools/set_pins.py                       # 预演（app/data/family.db）
    python tools/set_pins.py --db 路径              # 换一个库
    python tools/set_pins.py --pw 5678              # 换个口令（默认 1234）
    python tools/set_pins.py --all                 # 连家长一起改（默认只动孩子）
    python tools/set_pins.py --apply               # 真改

在 NAS 上跑（容器已经起来的机器）：

    docker cp tools/set_pins.py family-points:/srv/
    docker exec -it family-points python /srv/set_pins.py            # 先看
    docker exec -it family-points python /srv/set_pins.py --apply    # 再改

容器里的库在 /data/family.db，环境变量已经设好了，不给 --db 就找它。

改完记得提醒本人：登录之后在「我的 → 改密码」里换成自己的。这个脚本只在
交接那一下有用，不是给日常用的 —— 全家一个口令，谁都能进谁的号。
"""
import argparse
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))


def load(db_path):
    """连库。环境变量必须在 import db 之前设好，db.py 是模块级读的。"""
    if db_path:
        p = Path(db_path).expanduser().resolve()
        if not p.is_file():
            print("找不到这个库：%s" % p)
            sys.exit(1)
        os.environ["FAMILY_DB"] = str(p)
        os.environ.setdefault("FAMILY_DATA_DIR", str(p.parent))
    import db as D
    D.init_db(verbose=False)      # 空跑；顺带把库升到当前版本
    return D


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--db", default=None, help="要改哪个库（默认 app/data/family.db）")
    ap.add_argument("--pw", default="1234", help="统一改成什么（默认 1234）")
    ap.add_argument("--all", action="store_true", help="连家长一起改（默认只动孩子）")
    ap.add_argument("--apply", action="store_true", help="真改。不加就是预演")
    args = ap.parse_args()

    D = load(args.db)
    from api.auth import hash_password, check_pwd_rule

    # 先按规则验一遍。手滑传个 --pw 12，在这儿喊停比改完一半再喊停好。
    try:
        check_pwd_rule(args.pw, "child")
    except Exception as e:
        print("这个口令孩子用不了：%s" % getattr(e, "message", e))
        print("孩子那条规则是正好 4 位纯数字（登录页给的是数字键盘）。")
        sys.exit(1)

    rows = D.query("SELECT * FROM member WHERE active=1 ORDER BY sort, id")
    who = rows if args.all else [r for r in rows if r["role"] == "child"]
    if not who:
        print("这个库里没有要改的人（%s）。" % ("一个成员都没有" if not rows
                                              else "没有孩子，加 --all 才轮到家长"))
        return

    print("库：%s" % D.DB_PATH)
    print("口令：%s　范围：%s" % (args.pw, "所有人" if args.all else "只有孩子"))
    print("")
    for r in rows:
        mark = "改" if r in who else "　留"
        print("  [%s] %s　%s　%s" % (
            mark, r["name"],
            "家长" if r["role"] != "child" else "孩子",
            "现在有密码" if r["password_hash"] else "现在没密码"))

    if not args.apply:
        print("")
        print("上面是预演，一个字都没改。要真改，命令后面加 --apply。")
        print("改完让本人登录后在「我的 → 改密码」里换成自己的。")
        return

    h = hash_password(args.pw)
    n = 0
    for r in who:
        D.execute("UPDATE member SET password_hash=? WHERE id=?", (h, r["id"]))
        # 改密码就该把老会话踢掉，不然别人手上那台还连着。
        D.execute("DELETE FROM session WHERE member_id=?", (r["id"],))
        n += 1
    print("")
    print("改完了：%d 个人，口令都是 %s。" % (n, args.pw))
    print("原先登录着的设备都被踢了，得重新进一次。")
    print("提醒他们登录后在「我的 → 改密码」里换成自己的。")


if __name__ == "__main__":
    main()
