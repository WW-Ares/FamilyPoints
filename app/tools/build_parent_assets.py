# -*- coding: utf-8 -*-
"""一次性脚本：把「家长端 UI 交付包」里的图标搬进 app/web/parent/，
并生成 app/web/parent-icons.js（雪碧图 + 每个图标的 viewBox 表）。

跟孩子端那份 build_candy_assets.py 是同一套路，只有一处不同：
家长端的图标不是同一张版心，22 / 32 / 34 / 46 都有（器物小图、带底圆的大图、
头像），所以光靠雪碧图不够，还得把 viewBox 一起发出去 —— 前端拼 <svg> 时
要用它自己的版心，写死 24 会把图形裁掉一圈。

另一处坑：交付包里有个别图标带 <clipPath id="clip_0">。几个图标塞进同一张
雪碧图，id 就会撞车，后一个引用到的其实是前一个的裁剪区，图形会缺角。
这里统一把图标内部的 id 加图标名前缀（含 url(#...) 引用），一次性解决。

生成物别手改，改图标请改 web/parent/*.svg 再跑一遍这个脚本。
"""
import json
import re
import shutil
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
ROOT = APP.parent
SRC = ROOT / "旧版历史备份" / "05-设计交付包" / "家长端UI交付包" / "assets"
DST = APP / "web" / "parent"
OUT = APP / "web" / "parent-icons.js"


def namespace_ids(body, prefix):
    """把图标内部的 id 与引用加上前缀，几份图标同页时不打架。"""
    ids = re.findall(r'\sid="([^"]+)"', body)
    for i in ids:
        body = body.replace('id="%s"' % i, 'id="%s--%s"' % (prefix, i))
        body = body.replace('url(#%s)' % i, 'url(#%s--%s)' % (prefix, i))
        body = body.replace('href="#%s"' % i, 'href="#%s--%s"' % (prefix, i))
    return body


def main():
    if not SRC.is_dir():
        print("找不到交付包：%s" % SRC)
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    files = sorted((SRC / "icons").glob("*.svg"))
    if not files:
        print("交付包里没有图标")
        return 1

    symbols, names, boxes = [], [], {}
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
        boxes[name] = vb.group(1)
        body = re.sub(r"\n\s+", "", body.strip())
        body = namespace_ids(body, name)
        symbols.append('<symbol id="%s" viewBox="%s">%s</symbol>'
                       % (name, vb.group(1), body))
        shutil.copyfile(f, DST / f.name)

    deco = SRC / "deco-candy-island.svg"
    if deco.is_file():
        shutil.copyfile(deco, DST / "deco-candy-island.svg")

    lines = []
    lines.append("/* 家长端图标雪碧图。")
    lines.append(" * 由 tools/build_parent_assets.py 生成，源文件在 web/parent/*.svg，别手改。")
    lines.append(" *")
    lines.append(" * 图形全部手绘，无第三方素材，无授权问题。")
    lines.append(" * symbol 里不带 color，颜色一律由调用处的 pic(name, size, cls) 给；")
    lines.append(" * 版心不统一，所以另发一份 PARENT_VB，拼 <svg> 时照抄。")
    lines.append(" */")
    lines.append("var PARENT_ICONS = " + json.dumps(names, ensure_ascii=False) + ";")
    lines.append("var PARENT_VB = " + json.dumps(boxes, ensure_ascii=False) + ";")
    lines.append("var PARENT_SPRITE = '<svg xmlns=\"http://www.w3.org/2000/svg\" "
                 "style=\"position:absolute;width:0;height:0\" aria-hidden=\"true\">" +
                 "".join(symbols).replace("'", "\\'") + "</svg>';")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print("图标 %d 个 -> %s" % (len(names), DST.relative_to(APP)))
    print("雪碧图 -> %s（%d 字符）" % (OUT.relative_to(APP), OUT.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
