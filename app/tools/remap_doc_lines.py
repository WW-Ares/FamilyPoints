# -*- coding: utf-8 -*-
"""把《项目当前开发文档》里的 `文件:行号` 从上一个提交重排到当前工作区。

第十节第 2 条写着「本文件里的行号会漂，核对时以函数名和关键字为准」。漂是真的会漂：
随便在 `engine.py` 前半段插六行,后面两百处引用一起失灵。人工核一遍两百处没人受得了,
但不核又等于把这份文档最有用的那部分（「这条规则在代码哪一行」）慢慢废掉。

做法不靠猜：`git show HEAD:<文件>` 取出上一版,拿那里第 N 行的**原文**当锚,
去当前文件里找同一行。一行内容在这个项目里基本是唯一的,找到了就是位移后的位置。
所以这套只在「上一版 == 文档写作时的版本」时成立 —— 提交前跑,别攒三个提交再跑。

用法：
    python tools/remap_doc_lines.py              # 只报告改哪些，不写盘（默认）
    python tools/remap_doc_lines.py --apply      # 真写盘

**默认不写盘，是故意的。** 这个脚本一个提交周期里只该跑一次：跑完文档里的行号已经
是新坐标了，再跑一遍就变成拿新坐标去套旧版本，会把刚修好的又推错一截。所以第一遍
一定是看报告，报告里每条都带着「改前那一行长什么样」，指错了函数一眼就能看出来。

三种情况会跳过并逐条报告,需要人看一眼：
  · 锚行太短或是空行（没有辨识度）
  · 当前文件里找不到那一行（这一行本身被改过了 —— 那就得手工重新指定）
  · 同一行内容出现多次（取离旧行号最近的那个,可能取错）

它只改行号,不改文字。规则变了、口径变了,该改的文字还得自己写。
"""
import argparse
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC_REL = "docs/项目当前开发文档.md"
REF = re.compile(r"`([A-Za-z0-9_./]+\.(?:py|js|css|md|sql|html)):(\d+)(?:-(\d+))?`")

# 没进 git 的新文件也要认（第一次加进来时 HEAD 里没有）
EXTRA = set()


def changed_files(ref):
    """本次动过、且在 HEAD 里存在的文件。都没动就直接退出。"""
    r = subprocess.run(["git", "diff", "--name-only", ref], cwd=ROOT,
                       capture_output=True)
    if r.returncode:
        return None
    out = set()
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        p = line.strip()
        if p and p.startswith("app/"):
            out.add(p)
    return out | EXTRA


def head_lines(path, ref):
    r = subprocess.run(["git", "show", "%s:%s" % (ref, path)], cwd=ROOT,
                       capture_output=True)
    return None if r.returncode else r.stdout.decode("utf-8", "replace").splitlines()


def cur_lines(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def locate(cur, anchor, near):
    """唯一命中直接用；多处命中取离旧行号最近的。返回 (行号, 命中数)。"""
    hits = [i for i, l in enumerate(cur) if l.strip() == anchor and l.strip()]
    if not hits:
        return None, 0
    hits.sort(key=lambda i: abs(i + 1 - near))
    return hits[0] + 1, len(hits)


def main():
    ap = argparse.ArgumentParser(description="按上一版重排开发文档里的行号")
    ap.add_argument("ref", nargs="?", default="HEAD", help="拿哪一版当基准，默认 HEAD")
    ap.add_argument("--apply", action="store_true", help="真写盘；不加就是干跑")
    args = ap.parse_args()

    changed = changed_files(args.ref)
    if changed is None:
        print("读不到 %s 的改动清单，确认在仓库根目录附近、且这是个 git 仓库。" % args.ref)
        return 1
    if not changed:
        print("%s 之后 app/ 下一处也没动，不用重排。" % args.ref)
        return 0

    doc_path = os.path.join(ROOT, DOC_REL)
    doc = io.open(doc_path, encoding="utf-8").read()

    hcache, ccache, plan, notes = {}, {}, {}, []

    for m in REF.finditer(doc):
        path, a, b = m.group(1), int(m.group(2)), m.group(3)
        full = path if path.startswith("app/") else "app/" + path
        if full not in changed or not os.path.isfile(os.path.join(ROOT, full)):
            continue
        if full not in hcache:
            hcache[full] = head_lines(full, args.ref)
        if full not in ccache:
            ccache[full] = cur_lines(full)
        H, C = hcache[full], ccache[full]
        if H is None:
            notes.append("跳过 %s:%d（%s 里没有这个文件，大概是新加的）" % (path, a, args.ref))
            continue
        anchor = H[a - 1].strip() if a <= len(H) else ""
        if len(anchor) < 6:
            notes.append("跳过 %s:%d（锚行是空行或太短，没有辨识度）" % (path, a))
            continue
        na, hits = locate(C, anchor, a)
        if na is None:
            notes.append("找不到 %s:%d（这一行本身被改过了，得手工指定：%s）"
                         % (path, a, anchor[:50]))
            continue
        nb = None
        if b:
            ab = H[int(b) - 1].strip() if int(b) <= len(H) else ""
            if len(ab) >= 6:
                nb, _ = locate(C, ab, int(b))
            if nb is None:
                nb = int(b) + (na - a)
                notes.append("%s:%s-%s 末端锚没定位到，照头部位移 %+d 平移"
                             % (path, a, b, na - a))
        if hits > 1:
            notes.append("%s:%d 有 %d 处一模一样的内容，取了离旧行号最近的那个"
                         % (path, a, hits))
        plan[(full, a, b)] = (na, nb)

    applied = []

    def sub(m):
        path, a, b = m.group(1), int(m.group(2)), m.group(3)
        full = path if path.startswith("app/") else "app/" + path
        if (full, a, b) not in plan:
            return m.group(0)
        na, nb = plan[(full, a, b)]
        if na == a and (b is None or nb == int(b)):
            return m.group(0)
        applied.append((path, a, na, b, nb))
        return "`%s:%d%s`" % (path, na, ("-" + str(nb)) if b else "")

    new_doc = REF.sub(sub, doc)
    if args.apply:
        with io.open(doc_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_doc)

    print("%s：动过的文件 %d 个，重排 %d 处行号"
          % ("已写盘" if args.apply else "干跑", len(changed), len(applied)))
    for path, a, na, b, nb in applied:
        print("  %-26s %5d → %-5d%s" % (path, a, na,
                                        ("  区间 %s-%s" % (b, nb)) if b else ""))
    if notes:
        print("")
        print("要人看一眼的 %d 条：" % len(notes))
        for n in notes:
            print("  · %s" % n)
    print("")
    print("记着：这个脚本只算位移。哪一行指错了函数，它认不出来，得自己核。"
          + ("" if args.apply else "看完报告对得上，再跑一次加 --apply。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
