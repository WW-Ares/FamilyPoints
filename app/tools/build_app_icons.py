# -*- coding: utf-8 -*-
"""生成 web/ 下的应用图标：桌面图标、添加到主屏幕、浏览器标签页。

为什么要脚本而不是丢几张 png 进去：同一张图要出 6 个尺寸/形态（含一个留边距的
自适应版），手改一张就得记着另外几张也改，尺寸一多必然漏。这里「形状」只有一处
定义，重跑一遍全省同步。

产出（都落在 web/ 根目录，server.py 的 MIME 表里已有 .png/.ico/.webmanifest）：

    icon-192.png            192  普通图标
    icon-512.png            512  普通图标
    icon-512-maskable.png   512  安卓自适应图标，四周留安全边距
    apple-touch-icon.png    180  iOS 添加到主屏幕
    favicon.ico             16/32/48  老浏览器、Windows 快捷方式
    favicon.svg             矢量，浏览器标签页用（圆角）
    site.webmanifest        PWA 清单

图形：冒险橙底 + 白★。橙取自孩子端 --orange 那一档，星就是顶栏那个品牌★。
底色走 --orange-light → --orange → --orange-deep 的竖向渐变，跟登录页、孩子端
背景同一套暖色；纯平涂在浅色桌面上会显得发闷。

三个细节，别改坏：

1. png 一律满幅方形，不预先做圆角。iOS 和安卓都会自己套蒙版，图里自带圆角的话，
   蒙版外面会露出一圈黑边。要圆角的地方只有 favicon.svg —— 浏览器标签页不套蒙版。
2. maskable 那张星形要小一圈。安卓会把自适应图标裁成圆、水滴、方等各种形状，
   按普通尺寸画，五个尖角会被裁掉。
3. 4 倍超采样。PIL 画多边形没有抗锯齿，直接在 512 画布上画星形，五个尖角全是
   台阶；先在 4 倍画布上画再 LANCZOS 缩回去，边缘才干净。

依赖 Pillow，只有这个打包脚本用，运行时一个第三方包都没有。
用法：python tools/build_app_icons.py
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")

ORANGE_LIGHT = (255, 196, 107)   # --orange-light  #FFC46B
ORANGE = (255, 138, 61)          # --orange        #FF8A3D
ORANGE_DEEP = (232, 114, 42)     # --orange-deep   #E8722A
WHITE = (255, 255, 255)

STOPS = [(0.0, ORANGE_LIGHT), (0.52, ORANGE), (1.0, ORANGE_DEEP)]

SS = 4          # 超采样倍数
STAR_R = 0.375  # 普通图标：星形外接圆半径 / 画布边长
STAR_R_SAFE = 0.320  # 自适应图标：留出安全边距
STAR_INNER = 0.44    # 内接圆比例，越大星越胖。0.382 是尖五角，孩子端要圆润一点
STAR_ROUND = 0.09    # 尖角倒圆的宽度，同样为了圆润
STAR_DY = 0.0955     # 星形外接圆中心与视觉中心的偏差，补回来才看着正

APP_NAME = "家庭积分"
THEME = "#FF8A3D"        # 与 index.html 的 theme-color 同步
BG = "#FFFBF3"           # 孩子端 --bg-btm，启动闪屏底色


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _ramp(t):
    if t <= STOPS[0][0]:
        return STOPS[0][1]
    for i in range(len(STOPS) - 1):
        t0, c0 = STOPS[i]
        t1, c1 = STOPS[i + 1]
        if t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return _lerp(c0, c1, min(1.0, max(0.0, u)))
    return STOPS[-1][1]


def _gradient(size):
    """竖向三段渐变。先画一条 1px 宽的色带再横向拉平，比逐像素快得多。"""
    col = Image.new("RGB", (1, size))
    px = col.load()
    for y in range(size):
        px[0, y] = _ramp(y / (size - 1) if size > 1 else 0)
    return col.resize((size, size), Image.NEAREST)


def star_points(cx, cy, r_out, inner=STAR_INNER, dy=STAR_DY):
    """五角星，尖朝上。返回 10 个顶点（外/内交替）。"""
    pts = []
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        r = r_out if i % 2 == 0 else r_out * inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def draw_icon(size, star_ratio, rounded=0.0):
    """满幅橙底 + 白星。rounded>0 时把四角做成透明（只有 favicon 用）。"""
    S = size * SS
    img = _gradient(S).convert("RGBA")
    if rounded:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, S - 1, S - 1], radius=int(S * rounded), fill=255)
        img.putalpha(mask)
    d = ImageDraw.Draw(img)
    r = star_ratio * S
    pts = star_points(S / 2, S / 2 + STAR_DY * r, r)
    d.polygon(pts, fill=WHITE)
    # 描一圈同色再 joint="curve"，把十个角倒圆。PIL 的多边形本身没有圆角参数。
    d.line(list(pts) + [pts[0]], fill=WHITE, width=max(2, int(r * STAR_ROUND)),
           joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def _svg():
    """矢量版。浏览器标签页不套蒙版，所以这里带圆角，缩放也不糊。"""
    box, rx = 64.0, 14.5
    r = STAR_R * box
    pts = star_points(box / 2, box / 2 + STAR_DY * r, r)
    poly = " ".join("%.2f,%.2f" % (x, y) for x, y in pts)
    w = max(1.5, r * STAR_ROUND)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img">\n'
        '<title>家庭积分</title>\n'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">\n'
        '<stop offset="0" stop-color="#FFC46B"/>\n'
        '<stop offset=".52" stop-color="#FF8A3D"/>\n'
        '<stop offset="1" stop-color="#E8722A"/>\n'
        '</linearGradient></defs>\n'
        '<rect width="64" height="64" rx="%.1f" fill="url(#g)"/>\n'
        '<polygon points="%s" fill="#fff" stroke="#fff" stroke-width="%.2f" '
        'stroke-linejoin="round"/>\n'
        '</svg>\n' % (rx, poly, w))


def _manifest():
    return json.dumps({
        "name": APP_NAME,
        "short_name": APP_NAME,
        "description": "一家四口的每日积分、宝箱与心愿",
        "lang": "zh-CN",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": BG,
        "theme_color": THEME,
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-512-maskable.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, indent=2) + "\n"


def _png(img, name):
    path = os.path.join(WEB, name)
    img.save(path, "PNG", optimize=True)
    return path, os.path.getsize(path)


def main():
    out = []

    out.append(_png(draw_icon(192, STAR_R), "icon-192.png"))
    out.append(_png(draw_icon(512, STAR_R), "icon-512.png"))
    out.append(_png(draw_icon(512, STAR_R_SAFE), "icon-512-maskable.png"))
    out.append(_png(draw_icon(180, STAR_R), "apple-touch-icon.png"))

    # ico：从 256 缩，Pillow 内部对每个 size 走 thumbnail(LANCZOS)，比先缩再写干净。
    ico = os.path.join(WEB, "favicon.ico")
    draw_icon(256, STAR_R).save(ico, "ICO",
                                sizes=[(16, 16), (32, 32), (48, 48)])
    out.append((ico, os.path.getsize(ico)))

    svg = os.path.join(WEB, "favicon.svg")
    with open(svg, "w", encoding="utf-8", newline="\n") as f:
        f.write(_svg())
    out.append((svg, os.path.getsize(svg)))

    mf = os.path.join(WEB, "site.webmanifest")
    with open(mf, "w", encoding="utf-8", newline="\n") as f:
        f.write(_manifest())
    out.append((mf, os.path.getsize(mf)))

    for path, size in out:
        print("  %-28s %7.1f KB" % (os.path.basename(path), size / 1024.0))

    # 清单里点名的图，必须在磁盘上。少一个，安卓装到一半会白屏。
    m = json.loads(_manifest())
    missing = [i["src"] for i in m["icons"]
               if not os.path.isfile(os.path.join(WEB, i["src"]))]
    if missing:
        print("site.webmanifest 里写了但没生成：%s" % "、".join(missing))
        return 1

    print("")
    print("图标齐了。web/ 下共 %d 个文件。" % len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
