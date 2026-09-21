# -*- coding: utf-8 -*-
"""《项目当前开发文档》结构复查（七项判据）。

用法：python tools/verify_devdoc.py

v30 起规则真值不再是《规则全书》，改成 `docs/项目当前开发文档.md`，
这一份就是把老的 verify_doc_vNN.py 那套判据换到新文档上。

判据：
  1. 文档在位，头部写着「核对基准」
  2. 版本一致        文档里的 schema vNN 必须等于 seed_data.SCHEMA_VERSION
  3. 状态词干净      「未实现」「冲突」不许再当状态用（四个状态的说明句除外）
  4. 没有断掉的引用  「见待办 T」应为 0 处 —— 修完的条目要从待办删掉
  5. 待办表完整      第 8 节有 T1..T9 的清账行
  6. 行号不越界      文档里 `文件:行号` 引用的行号不能超过该文件总行数
  7. 前端文案在位    web/app.js 里那句「这一版」非空

两个反直觉的点：
  - 行号判据只能查「越界」，查不出「指到了别的函数」。改完代码记得顺手
    核对一遍受影响的行号，别指望脚本能替你判断语义。
  - 文档里出现旧版本号是正常的（沿革、归档说明），只有「核对基准」那一行
    代表当前版本。
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
UP = os.path.dirname(APP)

DOC = os.path.join(UP, "docs", "项目当前开发文档.md")
APPJS = os.path.join(APP, "web", "app.js")

fails = []
notes = []


def fail(msg):
    fails.append(msg)


def ok(msg):
    print("  [ok]   %s" % msg)


# ---- 1. 文档在位 -----------------------------------------------------------
if not os.path.exists(DOC):
    print("找不到 %s" % DOC)
    sys.exit(1)
doc = io.open(DOC, encoding="utf-8").read()
lines = doc.splitlines()
print("文档 %s，%d 行" % (os.path.relpath(DOC, UP), len(lines)))

m = re.search(r"核对基准\*\*：schema v(\d+)", doc)
if not m:
    fail("头部找不到「核对基准：schema vNN」")
    doc_ver = None
else:
    doc_ver = m.group(1)
    ok("核对基准写着 schema v%s" % doc_ver)

# ---- 2. 版本一致 -----------------------------------------------------------
sys.path.insert(0, APP)
import seed_data  # noqa: E402

code_ver = str(seed_data.SCHEMA_VERSION)
if doc_ver and doc_ver != code_ver:
    fail("版本不一致：文档 v%s / seed_data v%s" % (doc_ver, code_ver))
elif doc_ver:
    ok("文档与 seed_data.SCHEMA_VERSION 都是 v%s" % code_ver)

# ---- 3. 状态词干净 ---------------------------------------------------------
bad = []
for i, ln in enumerate(lines, 1):
    if ln.startswith("状态标记："):
        continue                      # 这一行是四个状态的定义，允许出现
    if "未实现" in ln or "**冲突**" in ln:
        bad.append(i)
if bad:
    fail("还有状态词没清干净，行 %s" % "、".join(str(x) for x in bad[:8]))
else:
    ok("正文没有「未实现 / 冲突」状态词")

# ---- 4. 没有断掉的待办引用 -------------------------------------------------
stale = [i for i, ln in enumerate(lines, 1) if re.search(r"见待办\s*T\d", ln)]
if stale:
    fail("还有指向待办的引用，行 %s" % "、".join(str(x) for x in stale))
else:
    ok("没有「见待办 T*」这类断引用")

# ---- 5. 待办表完整 ---------------------------------------------------------
sec8 = doc.split("# 8. 待办", 1)
if len(sec8) < 2:
    fail("找不到第 8 节")
else:
    body8 = sec8[1].split("\n# ", 1)[0]
    if "当前为空" not in body8:
        fail("第 8 节没写明「当前为空」")
    missing = [t for t in ("T%d" % n for n in range(1, 10))
               if not re.search(r"^\|\s*%s\s*\|" % t, body8, re.M)]
    if missing:
        fail("第 8 节清账表少了 %s" % "、".join(missing))
    else:
        ok("第 8 节清账表 T1..T9 齐全，并写明当前为空")

# ---- 6. 行号不越界 ---------------------------------------------------------
REF = re.compile(r"`?([A-Za-z0-9_\-/\.]+\.(?:py|sql|js|md|html)):(\d+)(?:-(\d+))?`?")
seen, over, unfound = {}, [], []
for mm in REF.finditer(doc):
    rel, a, b = mm.group(1), int(mm.group(2)), mm.group(3)
    if b:
        a = max(a, int(b))
    if rel in seen:
        continue
    cand = None
    for base in (APP, UP, os.path.join(UP, "docs")):
        p = os.path.join(base, rel.replace("/", os.sep))
        if os.path.exists(p):
            cand = p
            break
    if not cand:
        unfound.append(rel)
        seen[rel] = True
        continue
    n = sum(1 for _ in io.open(cand, encoding="utf-8", errors="replace"))
    seen[rel] = True
    if a > n:
        over.append("%s:%d（该文件只有 %d 行）" % (rel, a, n))
if unfound:
    notes.append("文档里引用了找不到的文件：%s" % "、".join(sorted(set(unfound))))
if over:
    fail("行号越界：%s" % "；".join(over[:6]))
else:
    ok("行号引用都没越界（查了 %d 个文件）" % len(seen))

# ---- 7. 前端文案在位 -------------------------------------------------------
js = io.open(APPJS, encoding="utf-8").read()
mj = re.search(r"这一版：(.{0,40})", js)
if not mj or not mj.group(1).strip():
    fail("web/app.js 里「这一版」文案空了")
else:
    ok("web/app.js「这一版」文案在位")

# ---- 结论 -----------------------------------------------------------------
print("")
for n in notes:
    print("  [note] %s" % n)
if fails:
    print("=" * 56)
    for f in fails:
        print("  [FAIL] %s" % f)
    print("复查没通过：%d 项。" % len(fails))
    sys.exit(1)
print("=" * 56)
print("开发文档复查通过。")
