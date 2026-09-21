# -*- coding: utf-8 -*-
"""一次性脚本：把「孩子端 UI 交付包」里的图标搬进 app/web/candy/，
并生成 app/web/candy-icons.js（雪碧图 + 唯一的渲染出口 ic()）。

为什么要有这一步。交付包里的 43 个图标用 stroke="currentColor" 上色，
必须做成 SVG 雪碧图才能跟着文字颜色走；直接塞进 icons/<token>.svg 用 <img>
引的话，currentColor 会落成黑色，整套糖果色的换色能力就没了。

生成物别手改，改图标请改 web/candy/*.svg 再跑一遍这个脚本。
"""
import json
import re
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
ROOT = APP.parent
SRC = ROOT / "旧版历史备份" / "05-设计交付包" / "孩子端UI交付包" / "assets"
DST = APP / "web" / "candy"
OUT = APP / "web" / "candy-icons.js"

# 顺序不影响功能，只影响生成的 diff 好不好看
def main():
    if not SRC.is_dir():
        print("找不到交付包：%s" % SRC)
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    files = sorted((SRC / "icons").glob("*.svg"))
    if not files:
        print("交付包里没有图标")
        return 1

    symbols, names = [], []
    for f in files:
        raw = f.read_text(encoding="utf-8")
        m = re.search(r"<svg\b([^>]*)>(.*)</svg>", raw, re.S)
        if not m:
            print("这个文件不是认识的 svg：%s" % f.name)
            return 1
        attrs, body = m.group(1), m.group(2)
        vb = re.search(r'viewBox="([^"]+)"', attrs)
        if not vb:
            print("没有 viewBox：%s" % f.name)
            return 1
        name = f.stem
        names.append(name)
        body = body.strip()
        body = re.sub(r"\n\s+", "", body)          # 压成一行，省体积
        symbols.append('<symbol id="%s" viewBox="%s">%s</symbol>' % (name, vb.group(1), body))
        shutil.copyfile(f, DST / f.name)

    deco = SRC / "deco-stars.svg"
    if deco.is_file():
        shutil.copyfile(deco, DST / "deco-stars.svg")

    lines = []
    lines.append("/* 孩子端图标雪碧图。")
    lines.append(" * 由 tools/build_candy_assets.py 生成，源文件在 web/candy/*.svg，别手改。")
    lines.append(" *")
    lines.append(" * 图形全部手绘，无第三方素材，无授权问题。")
    lines.append(" * symbol 里不带 color，颜色一律由调用处的 ic(name, size, style) 给，")
    lines.append(" * 这样同一个图标能在橙卡上是白的、在蓝任务卡里是蓝的。")
    lines.append(" */")
    lines.append("var CANDY_ICONS = " + json.dumps(names, ensure_ascii=False) + ";")
    lines.append("var CANDY_SPRITE = '<svg xmlns=\"http://www.w3.org/2000/svg\" "
                 "style=\"position:absolute;width:0;height:0\" aria-hidden=\"true\">" +
                 "".join(symbols).replace("'", "\\'") + "</svg>';")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print("图标 %d 个 -> %s" % (len(names), DST.relative_to(APP)))
    print("雪碧图 -> %s（%d 字符）" % (OUT.relative_to(APP), OUT.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
