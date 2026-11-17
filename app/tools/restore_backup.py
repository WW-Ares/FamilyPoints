# -*- coding: utf-8 -*-
"""把一份 SQLite 快照恢复到当前库。

安全顺序：
  1. 只读校验源快照（integrity_check + schema + 关键表行数）
  2. 和当前库比行数，打印差异
  3. 给当前库做一份 pre-restore 快照
  4. 复制到同目录临时文件，os.replace 原子替换，删掉 -wal/-shm

默认只预演；真写要 --apply --yes --allow-live。
服务在跑时不要用 --allow-live：先 docker compose down。

用法：
  python app/tools/restore_backup.py --db /data/snapshots/family-2026-11-17.db
  python app/tools/restore_backup.py --db ... --apply --yes --allow-live
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

import db
import seed_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="要恢复的快照路径")
    ap.add_argument("--apply", action="store_true", help="真的写；不加只预演")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    ap.add_argument("--allow-live", action="store_true",
                    help="允许在服务运行时替换；正式环境不要用，先 down")
    args = ap.parse_args()

    src = os.path.abspath(args.db)
    if not os.path.isfile(src):
        print("找不到快照：%s" % src)
        return 1
    v = db.verify_snapshot(src, against_live=True)
    db.close_conn()  # Windows 上不关掉缓存连接，后面 os.replace 会被拒
    print("源快照：%s" % src)
    print("  校验：%s  schema=%s  counts=%s" %
          (v.get("detail"), v.get("schema_version"), v.get("counts")))
    print("  当前库：%s" % v.get("live_counts"))
    if not v.get("ok"):
        print("源快照没通过 integrity_check，拒绝恢复。")
        return 1
    if v.get("schema_version") and str(v["schema_version"]) > str(seed_data.SCHEMA_VERSION):
        print("源快照 schema %s 比当前代码 %s 新，拒绝恢复。"
              % (v["schema_version"], seed_data.SCHEMA_VERSION))
        return 1
    if v.get("match") is False:
        print("提示：源快照和当前库行数不一致，这是正常的（恢复的就是旧状态）。")

    if not args.apply:
        print("\n预演结束。要真写加 --apply --yes --allow-live（先停容器）。")
        return 0

    if not args.allow_live:
        print("\n拒绝在服务运行时替换。先 docker compose down，再在一次性容器里跑这个脚本。")
        return 1
    if not args.yes:
        print("\n真的要把当前库替换成这份快照？输入 RESTORE 继续：")
        if input().strip() != "RESTORE":
            print("取消。")
            return 1

    os.makedirs(db.SNAPSHOT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pre = os.path.join(db.SNAPSHOT_DIR, "pre-restore-%s.db" % stamp)
    try:
        live = sqlite3.connect(db.DB_PATH, timeout=5)
        dst = sqlite3.connect(pre)
        with dst:
            live.backup(dst)
        dst.close()
        live.close()
        db.close_conn()
    except sqlite3.Error as e:
        print("恢复前快照失败，停手：%s" % e)
        return 1
    print("恢复前快照：%s" % pre)

    fd, tmp = tempfile.mkstemp(prefix="restore-", suffix=".db",
                               dir=os.path.dirname(db.DB_PATH))
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, db.DB_PATH)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        print("替换失败：%s" % e)
        return 1
    for suf in ("-wal", "-shm"):
        try:
            os.remove(db.DB_PATH + suf)
        except OSError:
            pass
    print("恢复完成。起容器后跑 verify_backup.py 再确认一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
