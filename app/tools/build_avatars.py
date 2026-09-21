# -*- coding: utf-8 -*-
"""把「糖果冒险」那 40 张头像抄进 web/，并生成 web/avatars.js。

源文件在归档的 `旧版历史备份/05-设计交付包/登录与头像UI交付包/assets/avatars/`（40 个 96×96 手绘 SVG
+ 一份 index.json）。v36 之前这套头像是本脚本自己画的（12 张，头 + 肩、没有五官），
换皮之后改由设计交付包直接供货 —— 那 40 张有五官、眼镜、帽子、发饰，画得出
「谁是谁」，这是脚本拼几何体拼不出来的。

所以本脚本现在只做三件事：
  1. 把交付包里的 SVG 原样抄进 web/avatars/（顺手删掉不在清单里的旧文件）；
  2. 按 index.json 生成 web/avatars.js（界面读的就是这份清单）；
  3. 对着 seed_data.AVATAR_TOKENS 核一遍 —— 服务端那份清单漂了会当场报出来。

为什么不直接把图丢 web/avatars 里手改：这份头像是四个人的脸，也是登录页的
第一个界面。文件在交付包里有一份带配色说明的 index.json，改头像应该改那一份，
再跑这个脚本，两处一起更新。web/ 下的 SVG 与 avatars.js 都是生成物，别手改。

    python tools/build_avatars.py
"""
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(APP)
SRC = os.path.join(REPO, "旧版历史备份", "05-设计交付包",
                   "登录与头像UI交付包", "assets", "avatars")
OUT_SVG = os.path.join(APP, "web", "avatars")
OUT_JS = os.path.join(APP, "web", "avatars.js")


def main():
    index_path = os.path.join(SRC, "index.json")
    if not os.path.exists(index_path):
        raise SystemExit("找不到交付包：%s\n"
                         "头像的源文件在 旧版历史备份/05-设计交付包/登录与头像UI交付包/ 里，别删。" % SRC)
    with io.open(index_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    tokens = [it["id"] for it in items]

    # 服务端那份清单（seed_data.AVATAR_TOKENS）管着「谁算认识的头像」，迁移和
    # 界面回落都看它。两份漂了就会出现「明明有这张图，系统不认」，所以先对一遍。
    sys.path.insert(0, APP)
    import seed_data
    if sorted(tokens) != sorted(seed_data.AVATAR_TOKENS):
        only_here = sorted(set(tokens) - set(seed_data.AVATAR_TOKENS))
        only_there = sorted(set(seed_data.AVATAR_TOKENS) - set(tokens))
        raise SystemExit("头像清单对不上：只在交付包里的 %s；只在 seed_data 里的 %s"
                         % (only_here, only_there))

    if not os.path.isdir(OUT_SVG):
        os.makedirs(OUT_SVG)

    listing = []
    for it in items:
        tok = it["id"]
        src = os.path.join(SRC, tok + ".svg")
        if not os.path.exists(src):
            raise SystemExit("清单里有 %s，但交付包里没有 %s.svg" % (tok, tok))
        dst = os.path.join(OUT_SVG, tok + ".svg")
        with io.open(src, "r", encoding="utf-8") as f:
            svg = f.read()
        if not svg.endswith("\n"):
            svg += "\n"
        with io.open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(svg)
        # 名字里带上分组，列表页与搜索都直接用这一份，不用回去认前缀字母
        listing.append({"t": tok,
                        "l": "%s · %s" % (it["group"], it["name"]),
                        "g": it["group"],
                        "k": "%s %s %s" % (it["group"], it["name"], tok)})

    # 老头像（dad_1 / girl_3 那 12 张）已经没人用了，留着只会让「这图哪来的」更难查
    gone = []
    for fn in sorted(os.listdir(OUT_SVG)):
        if fn.endswith(".svg") and fn[:-4] not in tokens:
            os.remove(os.path.join(OUT_SVG, fn))
            gone.append(fn)
    if gone:
        print("清掉 %d 张旧头像：%s" % (len(gone), "、".join(gone)))

    js = ("/* 由 tools/build_avatars.py 生成，别手改。\n"
          "   图与清单的源在归档的 旧版历史备份/05-设计交付包/登录与头像UI交付包/assets/avatars/，\n"
          "   改那边再重跑脚本，web/avatars/ 与这份清单会一起重出。 */\n"
          "var AVATARS = " + json.dumps(listing, ensure_ascii=False, indent=0) + ";\n")
    with io.open(OUT_JS, "w", encoding="utf-8", newline="") as f:
        f.write(js)

    groups = {}
    for it in items:
        groups[it["group"]] = groups.get(it["group"], 0) + 1
    print("写了 %d 张头像 -> %s" % (len(items), OUT_SVG))
    print("  分组：%s" % "、".join("%s %d 张" % (k, v) for k, v in groups.items()))
    print("清单 -> %s" % OUT_JS)


if __name__ == "__main__":
    main()
