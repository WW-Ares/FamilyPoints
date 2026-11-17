# -*- coding: utf-8 -*-
"""只读校验备份：SQLite 快照或 JSON 导出。

用法：
  python app/tools/verify_backup.py
  python app/tools/verify_backup.py --db data/snapshots/family-2026-11-17.db
  python app/tools/verify_backup.py --json family-2026-11-17.json
  python app/tools/verify_backup.py --against-live
"""
import argparse
import hashlib
import json
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

import db


def verify_json(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != "family-points-export":
        return False, "不是 family-points-export"
    tables = d.get("tables") or {}
    counts = d.get("counts") or {}
    bad = [k for k, v in counts.items() if len(tables.get(k, [])) != v]
    if bad:
        return False, "counts 对不上：%s" % ", ".join(bad)
    payload = json.dumps(tables, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if d.get("content_sha256") != sha:
        return False, "content_sha256 对不上"
    return True, "表 %d 张，行 %d，schema %s，版本 %s" % (
        len(tables), sum(counts.values()), d.get("schema_version"), d.get("app_version"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="快照路径；不传就找最新")
    ap.add_argument("--json", help="JSON 导出路径")
    ap.add_argument("--against-live", action="store_true", help="和当前库比行数")
    args = ap.parse_args()

    if args.json:
        ok, detail = verify_json(args.json)
        print(("PASS " if ok else "FAIL ") + args.json + " " + detail)
        return 0 if ok else 1

    v = db.verify_snapshot(args.db, against_live=args.against_live)
    ok = bool(v.get("ok")) and v.get("match", True) is not False
    print(("PASS " if ok else "FAIL ") + (v.get("file") or "") + " " + str(v.get("detail") or ""))
    print("  schema=%s counts=%s" % (v.get("schema_version"), v.get("counts")))
    if args.against_live:
        print("  live=%s match=%s" % (v.get("live_counts"), v.get("match")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
